"""GET /health — liveness + provider/model surface; opt-in deep LLM round-trip."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps import ApiDeps, get_deps
from schemas import HealthResponse

router = APIRouter()


class _DeepEcho(BaseModel):
    """Trivial schema to round-trip through LLMClient.structured()."""

    ok: bool


@router.get("/health", response_model=HealthResponse)
async def get_health(
    deps: ApiDeps = Depends(get_deps),
    deep: bool = Query(False, description="If true, also run a 1-call LLM round-trip."),
) -> HealthResponse:
    base = HealthResponse(
        status="ok",
        llm_provider=deps.llm.provider,
        llm_model=deps.llm.model,
        embedder_provider=getattr(deps.embedder, "provider", "unknown"),
        embedder_model=deps.embedder.model,
        embedder_dims=deps.embedder.dims,
        vector_db_exists=deps.settings.vector_db_path.exists(),
        deep_check=None,
    )
    if not deep:
        return base

    t0 = time.monotonic()
    try:
        result = await asyncio.to_thread(
            deps.llm.structured,
            "You are a health probe. Respond with ok=true.",
            "Reply.",
            _DeepEcho,
        )
        return base.model_copy(
            update={
                "deep_check": {
                    "ok": bool(result.ok),
                    "llm_round_trip_ms": round((time.monotonic() - t0) * 1000, 2),
                }
            }
        )
    except Exception as e:  # noqa: BLE001 — surface any provider error in the response
        return base.model_copy(
            update={
                "deep_check": {
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "llm_round_trip_ms": round((time.monotonic() - t0) * 1000, 2),
                }
            }
        )
