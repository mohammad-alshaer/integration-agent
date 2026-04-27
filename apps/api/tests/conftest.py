"""Shared fixtures for the API tests.

Reuses evals._fakes (SmokeFakeLLM + ConstantEmbedder + smoke profiles) for
fully-offline, deterministic test runs. No GEMINI_API_KEY required.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.vector_store import SourceVectorStore
from api.config import Settings
from api.deps import ApiDeps, get_deps
from api.eval_lookup import invalidate_cache
from api.main import app as fastapi_app
from evals._fakes import (
    ConstantEmbedder,
    build_smoke_fake_llm,
    build_smoke_source_profile,
    build_smoke_target_profile,
    write_smoke_sample_parquets,
)
from schemas import SchemaProfile


@pytest.fixture
def smoke_source() -> SchemaProfile:
    return build_smoke_source_profile()


@pytest.fixture
def smoke_target() -> SchemaProfile:
    return build_smoke_target_profile()


@pytest.fixture
def smoke_sample_dir(tmp_path: Path) -> Path:
    d = tmp_path / "samples"
    write_smoke_sample_parquets(d)
    return d


@pytest.fixture
def api_deps(tmp_path: Path, smoke_source: SchemaProfile) -> Iterator[ApiDeps]:
    settings = Settings(
        vector_db_path=tmp_path / "vector.duckdb",
        reports_dir=tmp_path / "benchmarks",
    )
    embedder = ConstantEmbedder()
    llm = build_smoke_fake_llm()
    store = SourceVectorStore(settings.vector_db_path, embedder)
    store.add_columns(smoke_source)
    deps = ApiDeps(
        settings=settings,
        llm=llm,
        embedder=embedder,
        store=store,
        map_lock=asyncio.Lock(),
    )
    try:
        yield deps
    finally:
        store.close()


@pytest.fixture
def client(api_deps: ApiDeps) -> Iterator[TestClient]:
    """TestClient with deps overridden — lifespan is skipped (no `with` context)."""
    invalidate_cache()
    fastapi_app.dependency_overrides[get_deps] = lambda: api_deps
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()
        invalidate_cache()
