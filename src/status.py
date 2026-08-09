"""
status.py
---------
Print SQLite tracker: what X finished, what failed, generated drafts, approvals.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from db import counts, init_db, list_failed_normalize, list_generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Show X/Y job status from SQLite.")
    parser.add_argument("--failed", action="store_true", help="List failed normalize jobs")
    parser.add_argument("--generated", action="store_true", help="List recent Model Y drafts")
    args = parser.parse_args()

    init_db()
    print(f"[status] DB: {settings.app_db}")
    print()
    data = counts()
    for table, bucket in data.items():
        total = bucket.pop("_total", 0)
        parts = ", ".join(f"{k}={v}" for k, v in sorted(bucket.items())) or "(empty)"
        print(f"  {table:16} total={total:4}  {parts}")

    if args.failed:
        print("\n[status] Failed normalize jobs:")
        rows = list_failed_normalize()
        if not rows:
            print("  (none)")
        for r in rows:
            err = (r["error"] or "")[:120]
            print(f"  - {r['source_abs']}\n      attempts={r['attempts']} err={err}")
        print("\nRetry: python src/normalize.py --retry-failed")

    if args.generated:
        print("\n[status] Recent generated drafts:")
        rows = list_generated(15)
        if not rows:
            print("  (none)")
        for r in rows:
            print(
                f"  id={r['id']} status={r['status']} "
                f"x={r['available_to_x']} y={r['available_to_y']} "
                f"file={r['output_name']}"
            )
        print("\nApprove for X+Y: python src/approve.py --file <output.md>")
        print("Reject:           python src/approve.py --file <output.md> --reject")
        print("Unlearn:          python src/unlearn.py --file <path.md>")

    if not args.failed and not args.generated:
        print("\nTips:")
        print("  python src/status.py --failed")
        print("  python src/status.py --generated")
        print("  python src/normalize.py --retry-failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
