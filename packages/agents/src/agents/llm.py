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
import logging
import os
import time
from pathlib import Path
from typing import Protocol, TypeVar

import diskcache
from pydantic import BaseModel

log = logging.getLogger(__name__)

# Retry transient provider errors (5xx, 429). First retry after 1s, then 2s, 4s.
_RETRY_DELAYS_SEC = (1.0, 2.0, 4.0)
_TRANSIENT_HTTP_CODES = (429, 500, 502, 503, 504)

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
    """Google Gemini via the `google-genai` SDK. M1 default provider.

    Telemetry: every call updates `.last_tokens_in/out/cache_hit` (single most recent
    call) and `.total_tokens_in/out/calls/cache_hits` (running sums for the run).
    Read these after `.structured()` returns to attach per-spec telemetry, or at
    end-of-run to populate aggregate cost reports.
    """

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
        self.last_tokens_in: int = 0
        self.last_tokens_out: int = 0
        self.last_cache_hit: bool = False
        self.total_tokens_in: int = 0
        self.total_tokens_out: int = 0
        self.total_calls: int = 0
        self.total_cache_hits: int = 0

    def _record(self, tokens_in: int, tokens_out: int, cache_hit: bool) -> None:
        self.last_tokens_in = tokens_in
        self.last_tokens_out = tokens_out
        self.last_cache_hit = cache_hit
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_calls += 1
        if cache_hit:
            self.total_cache_hits += 1

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        key = prompt_cache_key(self.provider, self.model, system, user, schema.__name__)
        cached = get_cached(key)
        if cached is not None:
            self._record(0, 0, cache_hit=True)
            return schema.model_validate(cached)

        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
        )

        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS_SEC, None), start=1):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user,
                    config=config,
                )
                result: T = response.parsed
                tokens_in, tokens_out = _extract_usage(response)
                self._record(tokens_in, tokens_out, cache_hit=False)
                set_cached(key, result.model_dump())
                return result
            except Exception as exc:  # noqa: BLE001
                if not _is_transient(exc):
                    raise
                last_exc = exc
                if delay is None:
                    break
                log.warning(
                    "GeminiProvider transient error (attempt %d), retrying in %.1fs: %s",
                    attempt,
                    delay,
                    exc,
                )
                time.sleep(delay)

        assert last_exc is not None
        raise last_exc


def _extract_usage(response) -> tuple[int, int]:  # noqa: ANN001 — google-genai response type
    """Pull (prompt_tokens, completion_tokens) from a Gemini response. 0/0 on absence."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_token_count", 0) or 0
    out = getattr(usage, "candidates_token_count", 0) or 0
    return int(prompt), int(out)


def _is_transient(exc: Exception) -> bool:
    """Best-effort detection of retryable HTTP errors from google-genai."""
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_HTTP_CODES:
        return True
    msg = str(exc)
    return any(str(c) in msg for c in _TRANSIENT_HTTP_CODES) or "UNAVAILABLE" in msg
