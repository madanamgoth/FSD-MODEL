"""
generate.py
-----------
RAG generation entry point.

Flow:
  1) Take your feature brief (text)
  2) Embed the brief and SEARCH Chroma for similar FSD chunks  ← retrieval
  3) Build a prompt = fixed FSD template + examples + your brief
  4) Call Ollama (local LLM) to write a new FSD draft
  5) Save Markdown under output.dir from config.properties

Example:
  python src/generate.py --brief "SMS OTP: App calls API, API calls SMS gateway..."
  python src/generate.py --brief-file my_brief.txt --out sms_otp_fsd.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from db import init_db, record_generate, record_generate_failed
from ollama_client import check_ollama, generate_text
from prompting import SYSTEM_PROMPT, build_generation_prompt
from vectorstore import count_chunks, query_similar


def _slug(text: str, max_len: int = 40) -> str:
    """Make a short filename-friendly slug from the brief."""
    words = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (words[:max_len] or "draft").strip("_")


def generate_fsd(brief: str, out_name: str | None = None, brief_file: str | None = None) -> Path:
    """
    Full RAG generate:
      retrieve → prompt → Ollama → write file
    Returns the path of the written Markdown draft.
    """
    settings.ensure_dirs()
    init_db()

    ok, msg = check_ollama()
    if not ok:
        raise RuntimeError(msg)

    n = count_chunks()
    print(f"[generate] Chunks in index: {n}")
    if n == 0:
        print(
            "[generate] WARNING: index is empty. "
            "Run: python src/ingest.py --rebuild"
        )

    print(f"[generate] Retrieving top {settings.retrieve_top_k} similar chunk(s)...")
    hits = query_similar(brief, top_k=settings.retrieve_top_k)
    for i, hit in enumerate(hits, start=1):
        print(
            f"  [{i}] {hit.get('category') or '-'} | {hit['source']} | {hit['section']} "
            f"(distance={hit['distance']:.4f})"
        )

    prompt = build_generation_prompt(brief, hits)
    print(f"[generate] Calling Ollama model: {settings.ollama_model}")
    try:
        draft = generate_text(prompt, system=SYSTEM_PROMPT)
    except Exception as exc:
        record_generate_failed(brief=brief, brief_file=brief_file, error=str(exc))
        raise

    if out_name:
        out_path = Path(out_name)
        if not out_path.is_absolute():
            out_path = settings.output_dir / out_path
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = (
            settings.output_dir
            / f"{settings.generate_out_prefix}_{_slug(brief)}_{stamp}.md"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(draft + "\n", encoding="utf-8")
    job_id = record_generate(
        brief=brief,
        brief_file=brief_file,
        output_path=out_path,
        retrieved=hits,
        status="draft",
    )
    print(f"[generate] Draft saved: {out_path}")
    print(f"[generate] SQLite generate_jobs.id={job_id} status=draft (not yet available to X/Y)")
    print("[generate] When good: python src/approve.py --file \"{}\"".format(out_path))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an FSD draft using RAG + Ollama."
    )
    parser.add_argument(
        "--brief",
        type=str,
        help="Feature description text (the new topic facts)",
    )
    parser.add_argument(
        "--brief-file",
        type=str,
        help="Read the brief from a text file instead of --brief",
    )
    parser.add_argument(
        "--out",
        type=str,
        help="Output Markdown filename (placed under output.dir if relative)",
    )
    args = parser.parse_args()

    if args.brief_file:
        brief = Path(args.brief_file).read_text(encoding="utf-8")
    elif args.brief:
        brief = args.brief
    else:
        parser.error("Provide --brief or --brief-file")
        return 2

    if not brief.strip():
        print("[generate] Brief is empty.")
        return 1

    try:
        generate_fsd(brief, out_name=args.out, brief_file=args.brief_file)
    except Exception as exc:
        print(f"[generate] ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
