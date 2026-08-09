"""
unlearn.py
----------
Stop using a document for Model X / Y:
  - mark status=unlearned in SQLite
  - available_to_x=0, available_to_y=0
  - remove vectors from Chroma
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings
from db import init_db, mark_unlearned
from vectorstore import count_chunks, delete_by_source, resolve_source_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Unlearn a file (SQLite + Chroma).")
    parser.add_argument("--file", required=True, help="Path to .md / .docx to unlearn")
    parser.add_argument("--notes", help="Reason stored in feedback table")
    args = parser.parse_args()

    settings.ensure_dirs()
    init_db()

    path = Path(args.file)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()

    source_key = resolve_source_key(path)
    removed = delete_by_source(source_key)
    mark_unlearned(path, notes=args.notes)
    print(f"[unlearn] SQLite status=unlearned for {path}")
    print(f"[unlearn] Removed {removed} Chroma chunk(s) key={source_key}")
    print(f"[unlearn] Chunks left in index: {count_chunks()}")
    print("[unlearn] normalize/ingest will skip this file until you --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
