"""
db.py
-----
SQLite tracker for Model X / ingest / Model Y / user feedback / unlearn.

One file on disk (app.db from config.properties). Not in GitLab.
No extra database server.

Statuses used across tables:
  pending | running | done | failed | skipped | indexed | draft |
  approved | rejected | unlearned
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    -- source | normalized | generated | approved | pattern
    filename        TEXT NOT NULL,
    rel_path        TEXT,
    abs_path        TEXT NOT NULL UNIQUE,
    category        TEXT,
    title           TEXT,
    product         TEXT,
    feature_type    TEXT,
    actors_json     TEXT,
    summary         TEXT,
    parent_id       INTEGER,
    source_path     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    available_to_x  INTEGER NOT NULL DEFAULT 0,
    available_to_y  INTEGER NOT NULL DEFAULT 0,
    indexed         INTEGER NOT NULL DEFAULT 0,
    file_mtime      REAL,
    file_size       INTEGER,
    extra_json      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(parent_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS normalize_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER,
    source_abs      TEXT NOT NULL UNIQUE,
    source_rel      TEXT,
    source_mtime    REAL,
    source_size     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    windows_total   INTEGER,
    windows_ok      INTEGER,
    error           TEXT,
    output_md       TEXT,
    output_json     TEXT,
    model           TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER,
    md_abs          TEXT NOT NULL UNIQUE,
    md_rel          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    chunk_count     INTEGER,
    error           TEXT,
    chroma_source   TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS generate_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER,
    brief_text      TEXT,
    brief_file      TEXT,
    brief_preview   TEXT,
    output_abs      TEXT,
    output_name     TEXT,
    model           TEXT,
    retrieve_k      INTEGER,
    retrieved_json  TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    available_to_x  INTEGER NOT NULL DEFAULT 0,
    available_to_y  INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    generate_job_id INTEGER,
    document_id     INTEGER,
    verdict         TEXT NOT NULL,
    -- approved | rejected | unlearned
    notes           TEXT,
    fed_back_abs    TEXT,
    available_to_x  INTEGER NOT NULL DEFAULT 0,
    available_to_y  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(generate_job_id) REFERENCES generate_jobs(id),
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    at              TEXT NOT NULL,
    actor           TEXT,
    action          TEXT NOT NULL,
    document_id     INTEGER,
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_docs_kind_status ON documents(kind, status);
CREATE INDEX IF NOT EXISTS idx_docs_available_y ON documents(available_to_y);
CREATE INDEX IF NOT EXISTS idx_norm_status ON normalize_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_gen_status ON generate_jobs(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    settings.ensure_dirs()
    path = settings.app_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def _event(conn: sqlite3.Connection, action: str, document_id: int | None = None, detail: str = "", actor: str = "cli") -> None:
    conn.execute(
        "INSERT INTO events(at, actor, action, document_id, detail) VALUES (?,?,?,?,?)",
        (_now(), actor, action, document_id, detail[:4000] if detail else None),
    )


def upsert_document(
    *,
    kind: str,
    abs_path: str | Path,
    rel_path: str | None = None,
    filename: str | None = None,
    category: str | None = None,
    title: str | None = None,
    product: str | None = None,
    feature_type: str | None = None,
    actors: list | None = None,
    summary: str | None = None,
    parent_id: int | None = None,
    source_path: str | None = None,
    status: str = "pending",
    available_to_x: int | None = None,
    available_to_y: int | None = None,
    indexed: int | None = None,
    extra: dict | None = None,
) -> int:
    p = Path(abs_path).resolve()
    abs_s = str(p)
    name = filename or p.name
    rel = rel_path or name
    mtime = p.stat().st_mtime if p.is_file() else None
    size = p.stat().st_size if p.is_file() else None
    now = _now()
    actors_json = json.dumps(actors, ensure_ascii=False) if actors is not None else None
    extra_json = json.dumps(extra, ensure_ascii=False) if extra is not None else None

    with _connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE abs_path = ?", (abs_s,)).fetchone()
        if row:
            fields = {
                "kind": kind,
                "filename": name,
                "rel_path": rel,
                "category": category,
                "title": title,
                "product": product,
                "feature_type": feature_type,
                "actors_json": actors_json,
                "summary": summary,
                "parent_id": parent_id,
                "source_path": source_path,
                "status": status,
                "file_mtime": mtime,
                "file_size": size,
                "extra_json": extra_json,
                "updated_at": now,
            }
            if available_to_x is not None:
                fields["available_to_x"] = available_to_x
            if available_to_y is not None:
                fields["available_to_y"] = available_to_y
            if indexed is not None:
                fields["indexed"] = indexed
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE documents SET {sets} WHERE id = ?",
                [*fields.values(), row["id"]],
            )
            _event(conn, "document_update", row["id"], f"{kind}:{status}")
            return int(row["id"])

        ax = 0 if available_to_x is None else available_to_x
        ay = 0 if available_to_y is None else available_to_y
        ix = 0 if indexed is None else indexed
        cur = conn.execute(
            """
            INSERT INTO documents(
                kind, filename, rel_path, abs_path, category, title, product,
                feature_type, actors_json, summary, parent_id, source_path,
                status, available_to_x, available_to_y, indexed,
                file_mtime, file_size, extra_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                kind, name, rel, abs_s, category, title, product, feature_type,
                actors_json, summary, parent_id, source_path, status, ax, ay, ix,
                mtime, size, extra_json, now, now,
            ),
        )
        doc_id = int(cur.lastrowid)
        _event(conn, "document_insert", doc_id, f"{kind}:{status}")
        return doc_id


def get_document_by_path(abs_path: str | Path) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE abs_path = ?",
            (str(Path(abs_path).resolve()),),
        ).fetchone()


def set_document_flags(
    abs_path: str | Path,
    *,
    status: str | None = None,
    available_to_x: int | None = None,
    available_to_y: int | None = None,
    indexed: int | None = None,
) -> None:
    p = str(Path(abs_path).resolve())
    now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT id FROM documents WHERE abs_path = ?", (p,)).fetchone()
        if not row:
            return
        parts = ["updated_at = ?"]
        vals: list = [now]
        if status is not None:
            parts.append("status = ?")
            vals.append(status)
        if available_to_x is not None:
            parts.append("available_to_x = ?")
            vals.append(available_to_x)
        if available_to_y is not None:
            parts.append("available_to_y = ?")
            vals.append(available_to_y)
        if indexed is not None:
            parts.append("indexed = ?")
            vals.append(indexed)
        vals.append(row["id"])
        conn.execute(f"UPDATE documents SET {', '.join(parts)} WHERE id = ?", vals)
        _event(conn, "document_flags", row["id"], status or "")


def normalize_status(source_abs: str | Path) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM normalize_jobs WHERE source_abs = ?",
            (str(Path(source_abs).resolve()),),
        ).fetchone()
        return str(row["status"]) if row else None


def should_run_normalize(source_abs: str | Path, force: bool = False, retry_failed: bool = False) -> bool:
    st = normalize_status(source_abs)
    if force:
        return True
    if st is None:
        return True
    if st == "unlearned":
        return False
    if st == "done":
        return False
    if st == "failed":
        return retry_failed
    if st in {"pending", "running", "skipped"}:
        return True
    return False


def mark_normalize(
    source: Path,
    *,
    status: str,
    rel: str | None = None,
    error: str | None = None,
    windows_total: int | None = None,
    windows_ok: int | None = None,
    output_md: str | None = None,
    output_json: str | None = None,
    document_id: int | None = None,
) -> None:
    abs_s = str(source.resolve())
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, attempts FROM normalize_jobs WHERE source_abs = ?",
            (abs_s,),
        ).fetchone()
        attempts = (row["attempts"] + 1) if row and status == "running" else (row["attempts"] if row else 0)
        if status == "running" and not row:
            attempts = 1
        if row:
            conn.execute(
                """
                UPDATE normalize_jobs SET
                    document_id=?, source_rel=?, source_mtime=?, source_size=?,
                    status=?, attempts=?, windows_total=?, windows_ok=?, error=?,
                    output_md=?, output_json=?, model=?,
                    started_at=CASE WHEN ?='running' THEN ? ELSE started_at END,
                    finished_at=CASE WHEN ? IN ('done','failed','skipped','unlearned') THEN ? ELSE finished_at END,
                    updated_at=?
                WHERE id=?
                """,
                (
                    document_id, rel,
                    source.stat().st_mtime if source.is_file() else None,
                    source.stat().st_size if source.is_file() else None,
                    status, attempts, windows_total, windows_ok, error,
                    output_md, output_json, settings.normalize_model,
                    status, now, status, now, now, row["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO normalize_jobs(
                    document_id, source_abs, source_rel, source_mtime, source_size,
                    status, attempts, windows_total, windows_ok, error,
                    output_md, output_json, model, started_at, finished_at,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document_id, abs_s, rel,
                    source.stat().st_mtime if source.is_file() else None,
                    source.stat().st_size if source.is_file() else None,
                    status, attempts or (1 if status == "running" else 0),
                    windows_total, windows_ok, error, output_md, output_json,
                    settings.normalize_model,
                    now if status == "running" else None,
                    now if status in {"done", "failed", "skipped", "unlearned"} else None,
                    now, now,
                ),
            )
        _event(conn, f"normalize_{status}", document_id, abs_s)


def mark_ingest(
    md_path: Path,
    *,
    status: str,
    chunk_count: int | None = None,
    error: str | None = None,
    chroma_source: str | None = None,
    document_id: int | None = None,
) -> None:
    abs_s = str(md_path.resolve())
    now = _now()
    rel = None
    try:
        rel = str(md_path.resolve().relative_to(settings.ingest_dir.resolve()))
    except ValueError:
        rel = md_path.name
    with _connect() as conn:
        row = conn.execute("SELECT id FROM ingest_jobs WHERE md_abs = ?", (abs_s,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE ingest_jobs SET document_id=?, md_rel=?, status=?, chunk_count=?,
                    error=?, chroma_source=?,
                    started_at=CASE WHEN ?='running' THEN ? ELSE started_at END,
                    finished_at=CASE WHEN ? IN ('done','failed','unlearned') THEN ? ELSE finished_at END,
                    updated_at=?
                WHERE id=?
                """,
                (
                    document_id, rel, status, chunk_count, error, chroma_source,
                    status, now, status, now, now, row["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO ingest_jobs(
                    document_id, md_abs, md_rel, status, chunk_count, error,
                    chroma_source, started_at, finished_at, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document_id, abs_s, rel, status, chunk_count, error, chroma_source,
                    now if status == "running" else None,
                    now if status in {"done", "failed", "unlearned"} else None,
                    now, now,
                ),
            )
        if document_id and status == "done":
            conn.execute(
                "UPDATE documents SET indexed=1, status='indexed', updated_at=? WHERE id=?",
                (now, document_id),
            )
        if document_id and status == "unlearned":
            conn.execute(
                "UPDATE documents SET indexed=0, available_to_y=0, status='unlearned', updated_at=? WHERE id=?",
                (now, document_id),
            )
        _event(conn, f"ingest_{status}", document_id, abs_s)


def ingest_status(md_abs: str | Path) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM ingest_jobs WHERE md_abs = ?",
            (str(Path(md_abs).resolve()),),
        ).fetchone()
        return str(row["status"]) if row else None


def should_run_ingest(
    md_abs: str | Path,
    force: bool = False,
    retry_failed: bool = False,
    rebuild: bool = False,
) -> bool:
    """Same gate as Model X: no row = new file; done/unlearned = skip."""
    if is_unlearned_path(md_abs):
        return False
    if rebuild or force:
        return True
    st = ingest_status(md_abs)
    if st is None:
        return True
    if st == "unlearned":
        return False
    if st == "done":
        return False
    if st == "failed":
        return retry_failed
    if st in {"pending", "running"}:
        return True
    return False


def is_unlearned_path(abs_path: str | Path) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM documents WHERE abs_path = ?",
            (str(Path(abs_path).resolve()),),
        ).fetchone()
        return bool(row and row["status"] == "unlearned")


def record_generate(
    *,
    brief: str,
    brief_file: str | None,
    output_path: Path,
    retrieved: list[dict],
    status: str = "draft",
    error: str | None = None,
) -> int:
    abs_s = str(output_path.resolve())
    now = _now()
    preview = (brief or "")[:500]
    retrieved_slim = [
        {
            "source": h.get("source"),
            "section": h.get("section"),
            "category": h.get("category"),
            "distance": h.get("distance"),
        }
        for h in (retrieved or [])[:20]
    ]
    doc_id = upsert_document(
        kind="generated",
        abs_path=abs_s,
        rel_path=output_path.name,
        filename=output_path.name,
        title=output_path.stem,
        status=status,
        available_to_x=0,
        available_to_y=0,
        extra={"brief_preview": preview},
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO generate_jobs(
                document_id, brief_text, brief_file, brief_preview, output_abs,
                output_name, model, retrieve_k, retrieved_json, status,
                available_to_x, available_to_y, error, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id, brief[:20000] if brief else None, brief_file, preview,
                abs_s, output_path.name, settings.ollama_model,
                settings.retrieve_top_k, json.dumps(retrieved_slim, ensure_ascii=False),
                status, 0, 0, error, now, now,
            ),
        )
        job_id = int(cur.lastrowid)
        _event(conn, "generate_draft", doc_id, output_path.name)
    return job_id


def record_generate_failed(
    *,
    brief: str,
    brief_file: str | None,
    error: str,
) -> int:
    """Log a Model Y failure (no output file yet)."""
    now = _now()
    preview = (brief or "")[:500]
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO generate_jobs(
                document_id, brief_text, brief_file, brief_preview, output_abs,
                output_name, model, retrieve_k, retrieved_json, status,
                available_to_x, available_to_y, error, created_at, updated_at
            ) VALUES (NULL,?,?,?,NULL,NULL,?,?,NULL,'failed',0,0,?,?,?)
            """,
            (
                brief[:20000] if brief else None, brief_file, preview,
                settings.ollama_model, settings.retrieve_top_k,
                error[:4000], now, now,
            ),
        )
        job_id = int(cur.lastrowid)
        _event(conn, "generate_failed", None, error[:500])
    return job_id


def record_feedback(
    *,
    draft_path: Path,
    verdict: str,
    fed_back_path: Path | None = None,
    notes: str | None = None,
    available_to_x: int = 0,
    available_to_y: int = 0,
) -> None:
    draft_abs = str(draft_path.resolve())
    now = _now()
    with _connect() as conn:
        gen = conn.execute(
            "SELECT id, document_id FROM generate_jobs WHERE output_abs = ? ORDER BY id DESC LIMIT 1",
            (draft_abs,),
        ).fetchone()
        gen_id = gen["id"] if gen else None
        doc_id = gen["document_id"] if gen else None
        conn.execute(
            """
            INSERT INTO feedback(
                generate_job_id, document_id, verdict, notes, fed_back_abs,
                available_to_x, available_to_y, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                gen_id, doc_id, verdict, notes,
                str(fed_back_path.resolve()) if fed_back_path else None,
                available_to_x, available_to_y, now,
            ),
        )
        if gen_id:
            conn.execute(
                """
                UPDATE generate_jobs SET status=?, available_to_x=?, available_to_y=?, updated_at=?
                WHERE id=?
                """,
                (verdict, available_to_x, available_to_y, now, gen_id),
            )
        conn.execute(
            """
            UPDATE documents SET status=?, available_to_x=?, available_to_y=?, updated_at=?
            WHERE abs_path=?
            """,
            (verdict, available_to_x, available_to_y, now, draft_abs),
        )
        _event(conn, f"feedback_{verdict}", doc_id, draft_abs)


def mark_unlearned(abs_path: Path, notes: str | None = None) -> None:
    p = Path(abs_path).resolve()
    abs_s = str(p)
    now = _now()
    kind = "normalized" if p.suffix.lower() in {".md", ".markdown", ".txt"} else "source"
    doc_id = upsert_document(
        kind=kind,
        abs_path=p,
        filename=p.name,
        status="unlearned",
        available_to_x=0,
        available_to_y=0,
        indexed=0,
    )
    with _connect() as conn:
        conn.execute(
            """
            UPDATE documents SET status='unlearned', available_to_x=0, available_to_y=0,
                indexed=0, updated_at=? WHERE abs_path=?
            """,
            (now, abs_s),
        )
        conn.execute(
            "UPDATE normalize_jobs SET status='unlearned', updated_at=? WHERE source_abs=? OR output_md=?",
            (now, abs_s, abs_s),
        )
        conn.execute(
            "UPDATE ingest_jobs SET status='unlearned', updated_at=? WHERE md_abs=?",
            (now, abs_s),
        )
        conn.execute(
            "UPDATE generate_jobs SET status='unlearned', available_to_x=0, available_to_y=0, updated_at=? WHERE output_abs=?",
            (now, abs_s),
        )
        conn.execute(
            """
            INSERT INTO feedback(generate_job_id, document_id, verdict, notes, fed_back_abs,
                available_to_x, available_to_y, created_at)
            VALUES (NULL, ?, 'unlearned', ?, ?, 0, 0, ?)
            """,
            (doc_id, notes, abs_s, now),
        )
        _event(conn, "unlearn", doc_id, abs_s)


def counts() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with _connect() as conn:
        specs = [
            ("documents", "status"),
            ("normalize_jobs", "status"),
            ("ingest_jobs", "status"),
            ("generate_jobs", "status"),
            ("feedback", "verdict"),
        ]
        for table, col in specs:
            rows = conn.execute(
                f"SELECT {col} AS k, COUNT(*) c FROM {table} GROUP BY {col}"
            ).fetchall()
            bucket = {r["k"] or "?": r["c"] for r in rows}
            bucket["_total"] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            out[table] = bucket
    return out


def list_failed_normalize() -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM normalize_jobs WHERE status='failed' ORDER BY updated_at DESC"
            )
        )


def list_generated(limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                """
                SELECT * FROM generate_jobs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
        )


# Init on import so first script run creates the file.
init_db()
