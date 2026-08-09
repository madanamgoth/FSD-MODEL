"""
approve.py
----------
User said the generated FSD is GOOD.
  1) Record feedback in SQLite (available_to_x=1, available_to_y=1)
  2) Copy draft into normalized/APPROVED (library for Y, and X can see it)
  3) Re-index so Model Y retrieves it next time
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings
from db import init_db, mark_ingest, record_feedback, upsert_document
from documents import load_and_chunk_file
from vectorstore import count_chunks, delete_by_source, resolve_source_key, upsert_chunks


def approve_file(source_path: Path, dest_name: str | None = None, notes: str | None = None) -> Path:
    settings.ensure_dirs()
    init_db()

    if not source_path.is_file():
        raise FileNotFoundError(f"File not found: {source_path}")

    dest_name = dest_name or source_path.name
    if not dest_name.lower().endswith((".md", ".markdown", ".txt")):
        dest_name = dest_name + ".md"

    dest_dir = settings.normalized_dir / "APPROVED"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    shutil.copy2(source_path, dest)
    print(f"[approve] Copied to library (X+Y): {dest}")

    doc_id = upsert_document(
        kind="approved",
        abs_path=dest,
        rel_path=f"APPROVED/{dest_name}",
        filename=dest_name,
        category="APPROVED",
        title=dest.stem,
        source_path=str(source_path.resolve()),
        status="approved",
        available_to_x=1,
        available_to_y=1,
        indexed=0,
    )

    source_key = resolve_source_key(dest)
    removed = delete_by_source(source_key)
    if removed:
        print(f"[approve] Removed {removed} old chunk(s) before re-index")

    chunks = load_and_chunk_file(dest)
    written = upsert_chunks(chunks)
    mark_ingest(
        dest,
        status="done",
        chunk_count=written,
        chroma_source=source_key,
        document_id=doc_id,
    )
    record_feedback(
        draft_path=source_path,
        verdict="approved",
        fed_back_path=dest,
        notes=notes,
        available_to_x=1,
        available_to_y=1,
    )
    print(f"[approve] Indexed {written} chunk(s). available_to_x=1 available_to_y=1")
    print(f"[approve] Total chunks now in index: {count_chunks()}")
    return dest


def reject_file(source_path: Path, notes: str | None = None) -> None:
    init_db()
    record_feedback(
        draft_path=source_path,
        verdict="rejected",
        notes=notes,
        available_to_x=0,
        available_to_y=0,
    )
    print(f"[approve] Marked rejected (not fed to X/Y): {source_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Approve (or reject) a generated FSD; approved ones go to X+Y library."
    )
    parser.add_argument("--file", required=True, help="Generated draft path (output.dir)")
    parser.add_argument("--name", help="Filename inside normalized/APPROVED/")
    parser.add_argument("--notes", help="Optional comment stored in SQLite")
    parser.add_argument("--reject", action="store_true", help="Mark bad; do not feed to X/Y")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()

    try:
        if args.reject:
            reject_file(path, notes=args.notes)
        else:
            approve_file(path, dest_name=args.name, notes=args.notes)
    except Exception as exc:
        print(f"[approve] ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
