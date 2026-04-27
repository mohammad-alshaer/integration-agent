"""POST /map — wrap one graph.invoke() for one target table."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agents.graph import build_graph
from api.deps import ApiDeps, get_deps
from schemas import MappingSpec, MapRequest, MapResponse, PatternClassification, ValidationReport
from validator import Sandbox

log = logging.getLogger(__name__)
router = APIRouter()


def _resolve_target_fqns(req: MapRequest) -> list[str]:
    schema_table = req.target_table
    parts = schema_table.split(".", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail=f"target_table must be 'schema.table', got {schema_table!r}",
        )
    schema, table = parts
    fqns: list[str] = []
    for t in req.target_profile.tables:
        if t.table_schema == schema and t.table_name == table:
            fqns.extend(c.fqn for c in t.columns)
    return fqns


def _summarize(state: dict[str, Any], target_table: str, elapsed_sec: float) -> MapResponse:
    specs: list[MappingSpec] = list(state.get("specs", []))
    classifications: dict[str, PatternClassification] = state.get("classifications", {})
    reports: dict[str, ValidationReport] = state.get("validation_reports", {}) or {}

    classifications_summary = dict(Counter(pc.pattern.value for pc in classifications.values()))
    validation_summary: dict[str, int] | None = None
    if reports:
        passed = sum(1 for r in reports.values() if r.passed)
        validation_summary = {"passed": passed, "failed": len(reports) - passed}

    return MapResponse(
        target_table=target_table,
        specs=specs,
        classifications_summary=classifications_summary,
        validation_summary=validation_summary,
        retry_count=int(state.get("retry_count", 0)),
        elapsed_sec=elapsed_sec,
    )


def _run_graph_sync(req: MapRequest, target_fqns: list[str], deps: ApiDeps) -> dict[str, Any]:
    """Mirror of apps/worker/src/worker/cli.py:run lines 183-214 — sync, single-thread."""
    if req.rebuild_index:
        deps.store.reset()
    deps.store.add_columns(req.source_profile)

    sandbox: Sandbox | None = None
    if req.sample_dir:
        sandbox = Sandbox(Path(req.sample_dir))
    try:
        graph = build_graph(
            deps.embedder,
            deps.llm,
            deps.store,
            k_candidates=req.k_candidates,
            sandbox=sandbox,
            max_retries=req.max_retries,
        )
        return graph.invoke(
            {
                "source_profile": req.source_profile,
                "target_profile": req.target_profile,
                "target_fqns": target_fqns,
            }
        )
    finally:
        if sandbox is not None:
            sandbox.close()


@router.post("/map", response_model=MapResponse)
async def post_map(req: MapRequest, deps: ApiDeps = Depends(get_deps)) -> MapResponse:
    target_fqns = _resolve_target_fqns(req)
    if not target_fqns:
        raise HTTPException(
            status_code=404,
            detail=f"target table {req.target_table!r} has no columns in target_profile",
        )

    t0 = time.monotonic()
    # Serialize all /map requests — DuckDB connections held by the shared store
    # and the LLM provider's running token totals are not thread-safe.
    async with deps.map_lock:
        try:
            state = await asyncio.wait_for(
                asyncio.to_thread(_run_graph_sync, req, target_fqns, deps),
                timeout=deps.settings.map_timeout_sec,
            )
        except TimeoutError as e:
            raise HTTPException(
                status_code=504,
                detail=f"graph invocation exceeded {deps.settings.map_timeout_sec}s timeout",
            ) from e
    return _summarize(state, req.target_table, time.monotonic() - t0)
