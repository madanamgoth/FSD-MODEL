"""
config.py
---------
Loads settings from config.properties so folder names, model names,
and tuning knobs are NOT hardcoded in the rest of the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROPERTIES_FILE = PROJECT_ROOT / "config.properties"


def _parse_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing properties file: {path}\n"
            "Copy config.properties.example to config.properties."
        )

    props: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def _as_path(value: str) -> Path:
    p = Path(value)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _as_yn(value: str | None, default: bool = True) -> bool:
    """Parse Y/N (also yes/no/true/false/1/0). Empty → default."""
    if value is None or str(value).strip() == "":
        return default
    v = str(value).strip().upper()
    if v in {"Y", "YES", "TRUE", "1", "ON"}:
        return True
    if v in {"N", "NO", "FALSE", "0", "OFF"}:
        return False
    raise ValueError(f"Expected Y or N, got {value!r}")


@dataclass(frozen=True)
class Settings:
    """All runtime settings loaded from config.properties."""

    fsd_dir: Path
    normalized_dir: Path
    ingest_dir: Path
    fsd_exclude_dirs: tuple[str, ...]
    index_dir: Path
    output_dir: Path
    app_db: Path
    normalize_enabled: bool
    ingest_enabled: bool
    embedding_model: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: int
    normalize_model: str
    normalize_timeout_seconds: int
    normalize_window_chars: int
    normalize_window_overlap: int
    chunk_size: int
    chunk_overlap: int
    retrieve_top_k: int
    chroma_collection: str
    generate_out_prefix: str

    def ensure_dirs(self) -> None:
        self.fsd_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        self.ingest_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.app_db.parent.mkdir(parents=True, exist_ok=True)


def load_settings(properties_path: Path | None = None) -> Settings:
    path = properties_path or PROPERTIES_FILE
    p = _parse_properties(path)

    def require(key: str) -> str:
        if key not in p or p[key] == "":
            raise KeyError(f"Missing required property '{key}' in {path}")
        return p[key]

    exclude_raw = p.get("fsd.exclude.dirs", "")
    exclude_dirs = tuple(
        part.strip() for part in exclude_raw.split(",") if part.strip()
    )

    return Settings(
        fsd_dir=_as_path(require("fsd.dir")),
        normalized_dir=_as_path(require("normalized.dir")),
        ingest_dir=_as_path(require("ingest.dir")),
        fsd_exclude_dirs=exclude_dirs,
        index_dir=_as_path(require("index.dir")),
        output_dir=_as_path(require("output.dir")),
        app_db=_as_path(p.get("app.db", "data/app.db")),
        normalize_enabled=_as_yn(p.get("normalize.enabled"), True),
        ingest_enabled=_as_yn(p.get("ingest.enabled"), True),
        embedding_model=require("embedding.model"),
        ollama_base_url=require("ollama.base.url").rstrip("/"),
        ollama_model=require("ollama.model"),
        ollama_timeout_seconds=int(require("ollama.timeout.seconds")),
        normalize_model=require("normalize.model"),
        normalize_timeout_seconds=int(require("normalize.timeout.seconds")),
        normalize_window_chars=int(require("normalize.window.chars")),
        normalize_window_overlap=int(require("normalize.window.overlap")),
        chunk_size=int(require("chunk.size")),
        chunk_overlap=int(require("chunk.overlap")),
        retrieve_top_k=int(require("retrieve.top.k")),
        chroma_collection=require("chroma.collection"),
        generate_out_prefix=require("generate.out.prefix"),
    )


settings = load_settings()
