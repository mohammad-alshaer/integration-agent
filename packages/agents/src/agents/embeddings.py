"""Voyage embeddings client with SHA-256 content cache.

Voyage `voyage-3-large` is strong for technical / code-adjacent text (column
names, SQL types, descriptions). Free tier is generous (200M tokens) — for
this project the full AW2022 + AWDW2022 index costs ~100K tokens, effectively
free forever.

Caching:
  Each text's embedding is cached by sha256(model + text) under .cache/embeddings/.
  Re-embedding identical text is free and offline.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Protocol

import diskcache

log = logging.getLogger(__name__)

_CACHE_DIR = Path(".cache/embeddings")
_CACHE_DIR.parent.mkdir(exist_ok=True)
_cache = diskcache.Cache(str(_CACHE_DIR))

_RETRY_DELAYS_SEC = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)


def default_embedder() -> Embedder:
    """Construct the default embedder based on EMBEDDING_PROVIDER env var.

    Defaults to `gemini` because Voyage's no-credit-card free tier is too slow
    for this project's workload. Accepted values: `gemini` | `voyage`.
    """
    provider = os.environ.get("EMBEDDING_PROVIDER", "gemini").lower()
    if provider == "voyage":
        return VoyageEmbedder()
    return GeminiEmbedder()


def _content_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


class Embedder(Protocol):
    """Minimal interface for any embedding provider."""

    model: str
    dims: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""
        ...


class GeminiEmbedder:
    """Google Gemini embeddings via the `google-genai` SDK.

    Uses `gemini-embedding-001` by default. Free tier on Google AI Studio has
    much higher RPM limits than Voyage's no-credit-card tier, which makes it
    the sensible default for this project.
    """

    provider = "gemini"

    def __init__(
        self,
        model: str | None = None,
        *,
        dims: int = 1024,
        batch_size: int = 100,
        task_type: str = "RETRIEVAL_DOCUMENT",
        inter_batch_delay_sec: float = 1.0,
    ) -> None:
        from google import genai

        self.model = model or os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        self.dims = dims
        self.batch_size = batch_size
        self._task_type = task_type
        self._inter_batch_delay_sec = inter_batch_delay_sec
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = genai.Client(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        to_fetch_idx: list[int] = []
        to_fetch_text: list[str] = []

        for i, text in enumerate(texts):
            cached = _cache.get(_content_key(f"{self.model}:{self.dims}", text))
            if cached is not None:
                results[i] = cached
            else:
                to_fetch_idx.append(i)
                to_fetch_text.append(text)

        n_batches = (len(to_fetch_text) + self.batch_size - 1) // self.batch_size
        for bi_idx, start in enumerate(range(0, len(to_fetch_text), self.batch_size)):
            batch = to_fetch_text[start : start + self.batch_size]
            batch_idx = to_fetch_idx[start : start + self.batch_size]
            embeddings = self._embed_with_retry(batch)
            for bi, emb in zip(batch_idx, embeddings, strict=True):
                results[bi] = emb
                _cache.set(_content_key(f"{self.model}:{self.dims}", texts[bi]), emb)
            # Inter-batch delay to stay under free-tier RPM
            if self._inter_batch_delay_sec > 0 and bi_idx + 1 < n_batches:
                time.sleep(self._inter_batch_delay_sec)

        out: list[list[float]] = []
        for i, r in enumerate(results):
            if r is None:
                raise RuntimeError(f"embedding missing at index {i} for text {texts[i]!r}")
            out.append(r)
        return out

    def _embed_with_retry(self, batch: list[str]) -> list[list[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(
            task_type=self._task_type,
            output_dimensionality=self.dims,
        )
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS_SEC, None), start=1):
            try:
                resp = self._client.models.embed_content(
                    model=self.model,
                    contents=batch,
                    config=config,
                )
                return [list(e.values) for e in resp.embeddings]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if delay is None:
                    break
                log.warning(
                    "GeminiEmbedder transient error (attempt %d), retrying in %.1fs: %s",
                    attempt,
                    delay,
                    exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc


class VoyageEmbedder:
    """Voyage AI embeddings via the `voyageai` SDK.

    API key from VOYAGE_API_KEY env var.

    Note: Voyage's no-credit-card free tier caps at 3 RPM / 10K TPM, which is
    too slow to index a full schema in reasonable time. Use GeminiEmbedder
    unless you've added a payment method in the Voyage dashboard.
    """

    provider = "voyage"

    def __init__(
        self,
        model: str | None = None,
        *,
        dims: int = 1024,
        batch_size: int = 128,
        input_type: str = "document",
    ) -> None:
        import voyageai

        self.model = model or os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3-large")
        self.dims = dims
        self.batch_size = batch_size
        self._input_type = input_type
        api_key = os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = voyageai.Client(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text, hitting cache where possible."""
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        to_fetch_idx: list[int] = []
        to_fetch_text: list[str] = []

        # Cache lookup
        for i, text in enumerate(texts):
            cached = _cache.get(_content_key(self.model, text))
            if cached is not None:
                results[i] = cached
            else:
                to_fetch_idx.append(i)
                to_fetch_text.append(text)

        # Batch uncached calls
        for start in range(0, len(to_fetch_text), self.batch_size):
            batch = to_fetch_text[start : start + self.batch_size]
            batch_idx = to_fetch_idx[start : start + self.batch_size]
            embeddings = self._embed_with_retry(batch)
            for bi, emb in zip(batch_idx, embeddings, strict=True):
                results[bi] = emb
                _cache.set(_content_key(self.model, texts[bi]), emb)

        # Everything should now be filled
        out: list[list[float]] = []
        for i, r in enumerate(results):
            if r is None:
                raise RuntimeError(f"embedding missing at index {i} for text {texts[i]!r}")
            out.append(r)
        return out

    def _embed_with_retry(self, batch: list[str]) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS_SEC, None), start=1):
            try:
                resp = self._client.embed(batch, model=self.model, input_type=self._input_type)
                return resp.embeddings
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if delay is None:
                    break
                log.warning(
                    "VoyageEmbedder transient error (attempt %d), retrying in %.1fs: %s",
                    attempt,
                    delay,
                    exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc
