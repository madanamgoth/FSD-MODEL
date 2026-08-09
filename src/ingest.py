"""
ingest.py
---------
INDEX entry point for Model Y.

Reads **normalized Markdown** (Model X output) from ingest.dir,
chunks + embeds, writes Chroma under index.dir.

Do NOT point this at raw .docx after Model X exists.
Run normalize.py first.

Examples:
  python src/ingest.py
  python src/ingest.py --retry-failed
  python src/ingest.py --rebuild
  python src/ingest.py --file data/normalized/FSD-BASE/foo.md --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python src/ingest.py` by putting this folder on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings
from db import (
    init_db,
    mark_ingest,
    mark_unlearned,
    should_run_ingest,
    upsert_document,
)
from documents import iter_fsd_files, load_and_chunk_file
from vectorstore import (
    count_chunks,
    delete_by_source,
    resolve_source_key,
    upsert_chunks,
)


def ingest_files(
    paths: list[Path],
    rebuild: bool = False,
    force: bool = False,
    retry_failed: bool = False,
) -> None:
    """Load paths → chunk → embed → write to Chroma. Skips ingest_jobs=done unless force/rebuild."""
    settings.ensure_dirs()
    init_db()

    all_chunks = []
    per_file: list[tuple[Path, list]] = []
    skipped = 0
    for path in paths:
        if not path.is_file():
            print(f"[ingest] Skip (not a file): {path}")
            continue
        if path.suffix.lower() == ".json":
            continue
        if not should_run_ingest(
            path, force=force, retry_failed=retry_failed, rebuild=rebuild
        ):
            print(f"[ingest] Skip (db done/unlearned): {path.name}")
            skipped += 1
            continue
        print(f"[ingest] Reading: {path}")
        try:
            chunks = load_and_chunk_file(path)
        except Exception as exc:
            doc_id = upsert_document(
                kind="normalized", abs_path=path, filename=path.name,
                status="failed", available_to_y=0,
            )
            mark_ingest(path, status="failed", error=str(exc), document_id=doc_id)
            print(f"[ingest] ERROR reading {path}: {exc}")
            continue
        print(f"[ingest]   → {len(chunks)} chunk(s) category={chunks[0].category if chunks else '-'}")
        all_chunks.extend(chunks)
        per_file.append((path, chunks))

    if rebuild:
        print("[ingest] Rebuilding index from scratch...")
        # Wipe + write in one go
        from vectorstore import get_client

        client = get_client()
        try:
            client.delete_collection(settings.chroma_collection)
            print("[ingest] Old collection deleted.")
        except Exception:
            print("[ingest] No existing collection to delete (first run).")

        if not all_chunks:
            print("[ingest] No chunks to index. Index is empty.")
            return

        # Re-create by upserting batches
        batch_size = 64
        written = 0
        for i in range(0, len(all_chunks), batch_size):
            written += upsert_chunks(all_chunks[i : i + batch_size])
        print(f"[ingest] Rebuild complete. Chunks written: {written}")
    else:
        if not all_chunks:
            print(f"[ingest] Nothing to ingest. Skipped {skipped} already done/unlearned.")
            return
        # For non-rebuild: replace chunks per source so edits do not leave orphans
        sources = {c.source for c in all_chunks}
        for source in sources:
            removed = delete_by_source(source)
            if removed:
                print(f"[ingest] Replaced old chunks for {source} (removed {removed})")
        written = upsert_chunks(all_chunks)
        print(f"[ingest] Upsert complete. Chunks written: {written}")

    for path, chunks in per_file:
        doc_id = upsert_document(
            kind="normalized" if "APPROVED" not in path.parts else "approved",
            abs_path=path,
            filename=path.name,
            category=chunks[0].category if chunks else "",
            status="indexed",
            available_to_x=1,
            available_to_y=1,
            indexed=1,
        )
        mark_ingest(
            path,
            status="done",
            chunk_count=len(chunks),
            chroma_source=chunks[0].source if chunks else None,
            document_id=doc_id,
        )

    print(f"[ingest] Total chunks now in index: {count_chunks()}")
    print("[ingest] See: python src/status.py")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or update the FSD vector index (Chroma)."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete the whole index and recreate it from ingest.dir",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Ingest only this one file (path relative to project or absolute)",
    )
    parser.add_argument(
        "--delete",
        type=str,
        help="Unlearn: remove all index chunks for this source file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if ingest_jobs.status=done",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry rows with ingest_jobs.status=failed",
    )
    args = parser.parse_args()

    if not settings.ingest_enabled:
        print("[ingest] Disabled (ingest.enabled=N in config.properties). Exiting.")
        return 0

    settings.ensure_dirs()

    init_db()

    # --- Unlearn path ---
    if args.delete:
        target = Path(args.delete)
        if not target.is_absolute():
            target = (PROJECT_ROOT / target).resolve()
        source_key = resolve_source_key(target)
        removed = delete_by_source(source_key)
        mark_unlearned(target, notes="ingest --delete")
        mark_ingest(target, status="unlearned", chroma_source=source_key)
        print(f"[ingest] Unlearned {removed} chunk(s) for: {source_key}")
        print(f"[ingest] Total chunks now in index: {count_chunks()}")
        return 0

    # --- Choose which files to index ---
    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        paths = [path]
    else:
        paths = iter_fsd_files(settings.ingest_dir)
        print(f"[ingest] Found {len(paths)} file(s) in {settings.ingest_dir}")

    if not paths and not args.rebuild:
        print(
            f"[ingest] No files in {settings.ingest_dir}. "
            "Run: python src/normalize.py   then ingest again."
        )
        return 1

    ingest_files(
        paths,
        rebuild=args.rebuild,
        force=args.force,
        retry_failed=args.retry_failed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
