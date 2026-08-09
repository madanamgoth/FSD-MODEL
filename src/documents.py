"""
documents.py
------------
Load FSD files from disk (Markdown / PDF / Word) and split them into
smaller "chunks" that we can embed and store in the vector index.

Why chunk?
  Models and search work better on sections than on a 50-page file.
  We prefer splitting on Markdown headings (## ...) when present.
  For Word (.docx) we also extract TABLES as text (not only paragraphs).
  Images/diagrams are NOT indexed as pictures in this version — only text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from config import PROJECT_ROOT, settings


@dataclass
class DocumentChunk:
    """One piece of an FSD that will be embedded and indexed."""

    text: str
    source: str          # relative or absolute file path (for delete/learn)
    section: str         # heading name if we found one, else "body"
    chunk_id: str        # stable id: source + chunk index
    category: str = ""   # e.g. FSD-BASE, FSD-WORD-DOCUMENT, PATTERNS


SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}
# Old Word format — we warn and skip (convert to .docx first)
SKIP_SUFFIXES = {".doc"}


def _relative_source(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def category_for_path(path: Path) -> str:
    """
    Folder tag under ingest.dir / normalized.dir / fsd.dir, e.g.
      .../FSD-BASE/foo.md → FSD-BASE
      .../PATTERNS/x.md → PATTERNS
    """
    for root in (settings.ingest_dir, settings.normalized_dir, settings.fsd_dir):
        try:
            rel = path.resolve().relative_to(root.resolve())
            parts = rel.parts
            if len(parts) >= 2:
                return parts[0]
            return "root"
        except ValueError:
            continue
    return path.parent.name or "unknown"


def _table_to_text(table) -> str:
    """
    Convert a Word table into plain text rows.
    Merged cells often repeat the same value in python-docx — we de-dupe
    consecutive identical cell texts in a row.
    """
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        prev = None
        for cell in row.cells:
            value = " ".join(cell.text.split()).strip()
            if value == prev:
                continue
            prev = value
            cells.append(value if value else "")
        if any(cells):
            lines.append(" | ".join(cells))
    if not lines:
        return ""
    return "[TABLE]\n" + "\n".join(lines) + "\n[/TABLE]"


def _iter_docx_blocks(doc):
    """
    Yield paragraphs and tables in document order (not paragraphs-only).
    This keeps table content next to the surrounding narrative.
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _load_docx_text(path: Path) -> str:
    """
    Read .docx as text including tables.
    Also prints how many images were found (not indexed yet — Phase B).
    """
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    image_count = 0
    try:
        for rel in doc.part.rels.values():
            if "image" in getattr(rel, "reltype", ""):
                image_count += 1
    except Exception:
        image_count = 0

    table_count = 0
    for block in _iter_docx_blocks(doc):
        # duck-typing: Table has .rows, Paragraph has .text and .style
        if hasattr(block, "rows"):
            table_txt = _table_to_text(block)
            if table_txt:
                parts.append(table_txt)
                table_count += 1
        else:
            text = (block.text or "").strip()
            if not text:
                continue
            # Promote Word heading styles to Markdown so chunking can split
            style_name = ""
            try:
                style_name = (block.style.name or "") if block.style else ""
            except Exception:
                style_name = ""
            if style_name.startswith("Heading"):
                level = 2
                m = re.search(r"(\d+)", style_name)
                if m:
                    level = min(max(int(m.group(1)), 1), 6)
                parts.append("#" * level + " " + text)
            else:
                parts.append(text)

    if image_count:
        parts.append(
            f"[NOTE: This document contains {image_count} embedded image(s)/diagram(s). "
            "Image pixels are not indexed in v1; only surrounding text and tables are.]"
        )
    print(f"[documents] {path.name}: tables={table_count}, images={image_count} (images not indexed)")
    return "\n\n".join(parts)


def load_file_text(path: Path) -> str:
    """
    Read a single FSD file into plain text.
    Supported: .md / .txt / .pdf / .docx (with tables)
    """
    suffix = path.suffix.lower()

    if suffix in {".md", ".markdown", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)

    if suffix == ".docx":
        return _load_docx_text(path)

    if suffix in SKIP_SUFFIXES:
        raise ValueError(
            f"Old Word .doc is not supported: {path}. Convert to .docx first."
        )

    raise ValueError(f"Unsupported file type: {path}")


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """
    Split Markdown-ish text on lines that look like headings (# or ##).
    Returns list of (section_title, section_body).
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title = "body"
    current_lines: list[str] = []

    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")

    for line in lines:
        m = heading_re.match(line.strip())
        if m:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, body))
            current_title = m.group(2).strip() or "body"
            current_lines = [line]
        else:
            current_lines.append(line)

    body = "\n".join(current_lines).strip()
    if body:
        sections.append((current_title, body))

    if not sections and text.strip():
        sections.append(("body", text.strip()))

    return sections


def _window_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Sliding window over characters when a section is still too long."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def chunk_text(text: str, source: str, category: str = "") -> list[DocumentChunk]:
    """
    Turn one document's text into DocumentChunk objects using:
      1) heading-based sections
      2) window split if a section is still too long
    """
    size = settings.chunk_size
    overlap = settings.chunk_overlap
    results: list[DocumentChunk] = []
    idx = 0

    for section_title, section_body in _split_by_headings(text):
        pieces = _window_chunks(section_body, size, overlap)
        for piece in pieces:
            chunk_id = f"{source}:::{idx}"
            results.append(
                DocumentChunk(
                    text=piece,
                    source=source,
                    section=section_title,
                    chunk_id=chunk_id,
                    category=category,
                )
            )
            idx += 1

    return results


def _is_excluded(path: Path, root: Path) -> bool:
    """True if any path part matches fsd.exclude.dirs from config."""
    exclude = {x.strip().lower() for x in settings.fsd_exclude_dirs if x.strip()}
    if not exclude:
        return False
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return any(part.lower() in exclude for part in rel.parts)


def iter_fsd_files(folder: Path | None = None) -> list[Path]:
    """
    Recursively list supported FSD files.
    Default folder is ingest.dir (normalized MD for Model Y).
    """
    root = folder or settings.ingest_dir
    if not root.is_dir():
        return []

    supported: list[Path] = []
    skipped_doc: list[Path] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _is_excluded(path, root):
            continue
        suffix = path.suffix.lower()
        if suffix in SKIP_SUFFIXES:
            skipped_doc.append(path)
            continue
        if suffix in SUPPORTED_SUFFIXES:
            supported.append(path)

    if skipped_doc:
        print(f"[documents] Skipping {len(skipped_doc)} old .doc file(s) (convert to .docx):")
        for p in skipped_doc[:10]:
            print(f"  - {p}")
        if len(skipped_doc) > 10:
            print(f"  ... and {len(skipped_doc) - 10} more")

    return supported


def load_and_chunk_file(path: Path) -> list[DocumentChunk]:
    """Full pipeline for one file: read (with tables) → chunk."""
    text = load_file_text(path)
    source = _relative_source(path)
    category = category_for_path(path)
    return chunk_text(text, source=source, category=category)
