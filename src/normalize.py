"""
normalize.py
------------
MODEL X — streamline / sort raw FSDs into a fixed Markdown template.

Input:  fsd.dir  (raw .docx / .md)     e.g. data/fsds/FSD
Output: normalized.dir (.md + .json)   e.g. data/normalized

Does NOT train weights. Rewrites each document section-by-section so
Model Y can index a consistent library.

Examples:
  python src/normalize.py --limit 1
  python src/normalize.py --file data/fsds/FSD/FSD-BASE/foo.docx
  python src/normalize.py --force
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings
from documents import (
    SUPPORTED_SUFFIXES,
    category_for_path,
    iter_fsd_files,
    load_file_text,
)
from ollama_client import check_ollama, generate_text
from prompting import (
    FSD_SECTIONS,
    TAG_SYSTEM,
    build_normalize_window_prompt,
    build_tag_prompt,
    NORMALIZE_SYSTEM,
)
from db import (
    init_db,
    mark_normalize,
    set_document_flags,
    should_run_normalize,
    upsert_document,
)

SECTION_KEYS = [s.split(". ", 1)[-1] if ". " in s else s for s in FSD_SECTIONS]
HEADING_RE = re.compile(r"^##\s+(\d+\.\s+)?(.+?)\s*$", re.MULTILINE)


def _rel_under_fsd(path: Path) -> Path:
    try:
        return path.resolve().relative_to(settings.fsd_dir.resolve())
    except ValueError:
        return Path(path.name)


def _out_paths(src: Path) -> tuple[Path, Path]:
    rel = _rel_under_fsd(src)
    md_rel = rel.with_suffix(".md")
    json_rel = rel.with_suffix(".json")
    return settings.normalized_dir / md_rel, settings.normalized_dir / json_rel


def _window_text(text: str) -> list[str]:
    size = settings.normalize_window_chars
    overlap = settings.normalize_window_overlap
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _parse_sections(markdown: str) -> dict[str, str]:
    """Split Model X markdown into heading → body."""
    if markdown.strip().upper() == "SKIP":
        return {}
    found: dict[str, str] = {}
    matches = list(HEADING_RE.finditer(markdown))
    if not matches:
        return {}
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if not body:
            continue
        # Match to canonical section by number or name substring
        key = None
        num = m.group(1)
        if num:
            n = num.strip().rstrip(".")
            for canon in FSD_SECTIONS:
                if canon.startswith(n + "."):
                    key = canon
                    break
        if key is None:
            low = title.lower()
            for canon in FSD_SECTIONS:
                if canon.split(". ", 1)[-1].lower() in low or low in canon.lower():
                    key = canon
                    break
        if key is None:
            continue
        prev = found.get(key, "")
        found[key] = (prev + "\n\n" + body).strip() if prev else body
    return found


def _merge(dst: dict[str, str], extra: dict[str, str]) -> None:
    for k, v in extra.items():
        if not v.strip():
            continue
        if k not in dst:
            dst[k] = v.strip()
        elif v.strip() not in dst[k]:
            dst[k] = dst[k].rstrip() + "\n\n" + v.strip()


def _assemble_markdown(title: str, sections: dict[str, str]) -> str:
    lines = [f"# {title}", ""]
    for canon in FSD_SECTIONS:
        body = sections.get(canon, "").strip()
        if not body:
            body = "_Not specified in source document._"
        lines.append(f"## {canon}")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _extract_tags(source_name: str, preview: str) -> dict:
    try:
        raw = generate_text(
            build_tag_prompt(source_name, preview),
            system=TAG_SYSTEM,
            model=settings.normalize_model,
            timeout_seconds=settings.normalize_timeout_seconds,
            temperature=0.1,
        )
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
    except Exception as exc:
        print(f"[normalize] tag parse failed: {exc}")
    return {
        "title": Path(source_name).stem,
        "product": "",
        "feature_type": "other",
        "actors": [],
        "summary": "",
    }


def normalize_one(src: Path, force: bool = False, retry_failed: bool = False) -> Path | None:
    """Normalize one source file → normalized.dir .md (+ .json)."""
    out_md, out_json = _out_paths(src)
    rel = _rel_under_fsd(src)
    rel_s = str(rel).replace("\\", "/")
    kind = "pattern" if "PATTERNS" in rel.parts else "source"

    if not should_run_normalize(src, force=force, retry_failed=retry_failed):
        print(f"[normalize] Skip (db done/unlearned): {src.name}")
        return out_md if out_md.is_file() else None

    src_id = upsert_document(
        kind=kind,
        abs_path=src,
        rel_path=rel_s,
        filename=src.name,
        category=category_for_path(src),
        title=src.stem,
        status="running",
        source_path=str(src.resolve()),
        available_to_x=1,
        available_to_y=0,
    )
    mark_normalize(src, status="running", rel=rel_s, document_id=src_id)

    # PATTERNS are already clean Markdown — copy through
    if "PATTERNS" in rel.parts and src.suffix.lower() in {".md", ".markdown"}:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_md)
        upsert_document(
            kind="pattern",
            abs_path=out_md,
            rel_path=str(rel.with_suffix(".md")).replace("\\", "/"),
            filename=out_md.name,
            category="PATTERNS",
            title=out_md.stem,
            status="done",
            parent_id=src_id,
            source_path=str(src.resolve()),
            available_to_x=1,
            available_to_y=1,
        )
        set_document_flags(src, status="done")
        mark_normalize(
            src, status="done", rel=rel_s, document_id=src_id,
            output_md=str(out_md), windows_total=0, windows_ok=0,
        )
        print(f"[normalize] Copied pattern: {out_md}")
        return out_md

    print(f"[normalize] Extracting: {src}")
    try:
        text = load_file_text(src)
    except Exception as exc:
        mark_normalize(src, status="failed", rel=rel_s, document_id=src_id, error=str(exc))
        set_document_flags(src, status="failed")
        print(f"[normalize] ERROR extract {src}: {exc}")
        return None

    if not text.strip():
        mark_normalize(src, status="skipped", rel=rel_s, document_id=src_id, error="empty text")
        set_document_flags(src, status="skipped")
        print(f"[normalize] Empty text, skip: {src}")
        return None

    windows = _window_text(text)
    print(f"[normalize] {len(windows)} window(s) → Model X ({settings.normalize_model})")
    merged: dict[str, str] = {}
    windows_ok = 0
    last_err = None
    for i, window in enumerate(windows, start=1):
        print(f"[normalize]   window {i}/{len(windows)} ({len(window)} chars)")
        try:
            reply = generate_text(
                build_normalize_window_prompt(str(rel), window),
                system=NORMALIZE_SYSTEM,
                model=settings.normalize_model,
                timeout_seconds=settings.normalize_timeout_seconds,
                temperature=0.2,
            )
            windows_ok += 1
        except Exception as exc:
            last_err = str(exc)
            print(f"[normalize]   window {i} failed: {exc}")
            continue
        _merge(merged, _parse_sections(reply))

    if not merged and last_err:
        mark_normalize(
            src, status="failed", rel=rel_s, document_id=src_id,
            error=last_err, windows_total=len(windows), windows_ok=windows_ok,
        )
        set_document_flags(src, status="failed")
        print(f"[normalize] FAILED (no sections): {src}")
        return None

    title = src.stem.replace("-", " ").replace("_", " ")
    md = _assemble_markdown(title, merged)
    tags = _extract_tags(str(rel), text[:3000] + "\n\n" + md[:2000])
    tags["source"] = rel_s
    tags["category"] = category_for_path(src)
    tags["windows"] = len(windows)

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    out_json.write_text(json.dumps(tags, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    actors = tags.get("actors") if isinstance(tags.get("actors"), list) else []
    upsert_document(
        kind="normalized",
        abs_path=out_md,
        rel_path=str(rel.with_suffix(".md")).replace("\\", "/"),
        filename=out_md.name,
        category=tags.get("category") or category_for_path(src),
        title=tags.get("title") or title,
        product=tags.get("product"),
        feature_type=tags.get("feature_type"),
        actors=actors,
        summary=tags.get("summary"),
        parent_id=src_id,
        source_path=str(src.resolve()),
        status="done",
        available_to_x=1,
        available_to_y=1,
        extra=tags,
    )
    set_document_flags(src, status="done")
    mark_normalize(
        src, status="done", rel=rel_s, document_id=src_id,
        windows_total=len(windows), windows_ok=windows_ok,
        output_md=str(out_md), output_json=str(out_json),
    )
    print(f"[normalize] Wrote {out_md}")
    return out_md


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Model X: rewrite raw FSDs into canonical Markdown under normalized.dir"
    )
    parser.add_argument("--file", help="Normalize only this one source file")
    parser.add_argument("--force", action="store_true", help="Overwrite existing .md / redo db done")
    parser.add_argument("--retry-failed", action="store_true", help="Retry rows with status=failed")
    parser.add_argument("--limit", type=int, default=0, help="Max files this run (0 = all)")
    args = parser.parse_args()

    if not settings.normalize_enabled:
        print("[normalize] Disabled (normalize.enabled=N in config.properties). Exiting.")
        return 0

    settings.ensure_dirs()
    init_db()
    ok, msg = check_ollama()
    if not ok:
        print(f"[normalize] ERROR: {msg}")
        return 1

    print(f"[normalize] Model X: {settings.normalize_model}")
    print(f"[normalize] Input (raw):  {settings.fsd_dir}")
    print(f"[normalize] Output (md):  {settings.normalized_dir}")

    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        sources = [path]
    else:
        sources = [
            p
            for p in iter_fsd_files(settings.fsd_dir)
            if p.suffix.lower() in SUPPORTED_SUFFIXES
        ]
        print(f"[normalize] Found {len(sources)} source file(s)")

    if args.limit and args.limit > 0:
        sources = sources[: args.limit]
        print(f"[normalize] Limiting to {len(sources)} file(s)")

    if not sources:
        print("[normalize] No source files. Put .docx under fsd.dir")
        return 1

    done = 0
    for src in sources:
        if normalize_one(src, force=args.force, retry_failed=args.retry_failed):
            done += 1
    print(f"[normalize] Finished {done}/{len(sources)}")
    print("[normalize] See: python src/status.py")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
