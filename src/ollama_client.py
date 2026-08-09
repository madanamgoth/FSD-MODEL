"""
ollama_client.py
----------------
Calls the local Ollama HTTP API to generate text.

Base URL comes from config.properties.
Pass model= explicitly for Model X vs Model Y.
"""

from __future__ import annotations

import httpx

from config import settings


def check_ollama() -> tuple[bool, str]:
    url = f"{settings.ollama_base_url}/api/tags"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
        return True, "Ollama is reachable."
    except Exception as exc:
        return False, (
            f"Cannot reach Ollama at {settings.ollama_base_url}: {exc}\n"
            "Install Ollama, then pull: "
            f"{settings.ollama_model} and {settings.normalize_model}"
        )


def generate_text(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    timeout_seconds: int | None = None,
    temperature: float = 0.3,
) -> str:
    """Ask Ollama to complete a prompt (non-streaming)."""
    chosen = model or settings.ollama_model
    timeout_val = (
        timeout_seconds if timeout_seconds is not None else settings.ollama_timeout_seconds
    )
    payload = {
        "model": chosen,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    url = f"{settings.ollama_base_url}/api/generate"
    timeout = httpx.Timeout(timeout_val)

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    text = data.get("response", "")
    if not text.strip():
        raise RuntimeError(
            f"Ollama returned an empty response for model '{chosen}'. "
            "Check: ollama list"
        )
    return text.strip()
