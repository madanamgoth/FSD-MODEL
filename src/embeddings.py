"""
embeddings.py
-------------
Creates "embeddings" (lists of numbers that represent meaning of text)
by calling Ollama's embedding API.

Why Ollama (not sentence-transformers / PyTorch)?
  - One runtime to install (Ollama) for both chat + embeddings
  - Much smaller install on a 4 vCPU / 32 GB server
  - Model name comes from config.properties → embedding.model

Pull the embed model once:
  ollama pull nomic-embed-text
"""

from __future__ import annotations

import httpx

from config import settings


def _embed_one(client: httpx.Client, text: str) -> list[float]:
    """Ask Ollama to embed a single string."""
    url = f"{settings.ollama_base_url}/api/embeddings"
    response = client.post(
        url,
        json={"model": settings.embedding_model, "prompt": text},
    )
    response.raise_for_status()
    data = response.json()
    vector = data.get("embedding")
    if not vector:
        raise RuntimeError(
            f"Ollama returned no embedding for model '{settings.embedding_model}'. "
            f"Run: ollama pull {settings.embedding_model}"
        )
    return vector


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Convert a list of strings into a list of embedding vectors."""
    if not texts:
        return []

    timeout = httpx.Timeout(settings.ollama_timeout_seconds)
    vectors: list[list[float]] = []
    with httpx.Client(timeout=timeout) as client:
        for i, text in enumerate(texts, start=1):
            # Empty text would confuse the embed model — skip safely
            piece = text if text.strip() else " "
            vectors.append(_embed_one(client, piece))
            if i % 10 == 0 or i == len(texts):
                print(f"[embeddings] Embedded {i}/{len(texts)}")
    return vectors


def embed_query(text: str) -> list[float]:
    """Embed a single user brief / search query."""
    return embed_texts([text])[0]
