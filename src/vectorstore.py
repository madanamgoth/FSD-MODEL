"""
vectorstore.py
--------------
Talks to Chroma — our local vector database (the "index").

The index is NOT a scheduler. It is a folder of searchable embeddings.
We create / update / delete entries from ingest.py when YOU run it
(or when approve.py re-indexes after feedback).
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings
from documents import DocumentChunk
from embeddings import embed_texts


def get_client() -> chromadb.PersistentClient:
    """
    Open (or create) the Chroma database on disk at index.dir
    from config.properties.
    """
    settings.ensure_dirs()
    return chromadb.PersistentClient(
        path=str(settings.index_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection(client: chromadb.PersistentClient | None = None):
    """Get the named collection (creates it if missing)."""
    client = client or get_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},  # similar vectors = small distance
    )


def upsert_chunks(chunks: list[DocumentChunk]) -> int:
    """
    Insert or update chunks in Chroma.
    Returns how many chunks were written.
    """
    if not chunks:
        return 0

    collection = get_collection()
    ids = [c.chunk_id for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [
        {
            "source": c.source,
            "section": c.section,
            "category": c.category or "",
        }
        for c in chunks
    ]
    embeddings = embed_texts(documents)

    # Chroma upsert = insert if new, replace if same id already exists
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    return len(chunks)


def delete_by_source(source: str) -> int:
    """
    Unlearn: remove every chunk that came from a given source file.
    `source` should match the value stored at ingest time
    (usually a path relative to the project root).
    """
    collection = get_collection()
    # Fetch ids for this source, then delete them
    existing = collection.get(where={"source": source})
    ids = existing.get("ids") or []
    if not ids:
        return 0
    collection.delete(ids=ids)
    return len(ids)


def query_similar(query_text: str, top_k: int | None = None) -> list[dict]:
    """
    Search the index for chunks most similar to the user's brief.
    Returns a list of dicts: text, source, section, distance.
    """
    k = top_k if top_k is not None else settings.retrieve_top_k
    collection = get_collection()

    if collection.count() == 0:
        return []

    from embeddings import embed_query

    query_vec = embed_query(query_text)
    result = collection.query(
        query_embeddings=[query_vec],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict] = []
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    for text, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
                "text": text,
                "source": (meta or {}).get("source", ""),
                "section": (meta or {}).get("section", ""),
                "category": (meta or {}).get("category", ""),
                "distance": dist,
            }
        )
    return hits


def count_chunks() -> int:
    """How many chunks are currently in the index."""
    return get_collection().count()


def resolve_source_key(path: Path) -> str:
    """
    Convert a user-supplied file path into the same `source` string
    we store in Chroma (relative to project root when possible).
    """
    from config import PROJECT_ROOT

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)
