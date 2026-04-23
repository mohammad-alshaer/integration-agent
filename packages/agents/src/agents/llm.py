"""Provider-neutral LLM client + SHA-256 prompt-hash output cache.

Idempotency note: LLM outputs (any provider) are not deterministic even at
temperature=0 with a seed. We hash canonicalized (provider, model, system,
user, schema_name) and cache the validated Pydantic output. Same request ==
same cached result. This halves the cost of eval reruns and shields us from
free-tier rate limits while we iterate.

For M1 the only concrete implementation is GeminiProvider. Adding a
ClaudeProvider or OllamaProvider later is a one-file addition — the rest of
the codebase depends only on the LLMClient protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol, TypeVar

import diskcache
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_CACHE_DIR = Path(".cache/llm")
_CACHE_DIR.parent.mkdir(exist_ok=True)
_cache = diskcache.Cache(str(_CACHE_DIR))


class LLMClient(Protocol):
    """Minimal interface every provider must implement."""

    provider: str  # "gemini" | "claude" | "ollama" | ...
    model: str

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Call the LLM with system+user messages and a Pydantic response schema.

        Implementations MUST:
          - Check the prompt-hash cache before calling the provider.
          - On miss, call the provider, validate the response against `schema`,
            then write the result to the cache.
          - Return a validated `schema` instance.
        """
        ...


def prompt_cache_key(provider: str, model: str, system: str, user: str, schema_name: str) -> str:
    """SHA-256 of a canonicalized request envelope. Stable across Python versions."""
    canonical = json.dumps(
        {"p": provider, "m": model, "s": system, "u": user, "sc": schema_name},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_cached(key: str) -> dict | None:
    """Return the cached dict payload for `key`, or None on miss."""
    return _cache.get(key)


def set_cached(key: str, value: dict) -> None:
    """Store a dict payload (Pydantic `.model_dump()` output) under `key`."""
    _cache.set(key, value)


class GeminiProvider:
    """Google Gemini via the `google-genai` SDK. M1 default provider."""

    provider = "gemini"

    def __init__(self, model: str | None = None) -> None:
        # Lazy import so `agents` can be imported in contexts without google-genai installed
        from google import genai

        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = genai.Client(api_key=api_key)

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        key = prompt_cache_key(self.provider, self.model, system, user, schema.__name__)
        cached = get_cached(key)
        if cached is not None:
            return schema.model_validate(cached)

        from google.genai import types

        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2,
            ),
        )
        result: T = response.parsed
        set_cached(key, result.model_dump())
        return result
