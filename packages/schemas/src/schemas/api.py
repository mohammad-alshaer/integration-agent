"""HTTP contracts for the M3 FastAPI service layer.

Request/response shapes for `apps/api`. Reuses SchemaProfile / MappingSpec /
EvalReport from the existing contracts; defines only the API-specific envelopes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from schemas.mapping import MappingSpec
from schemas.profile import SchemaProfile


class MapRequest(BaseModel):
    """Body of POST /map. Profiles inline so a browser caller has no shared FS."""

    source_profile: SchemaProfile
    target_profile: SchemaProfile
    target_table: str = Field(
        ..., description="Single target table as 'schema.table' (e.g. 'dbo.DimCustomer')."
    )
    k_candidates: int = 15
    max_retries: int = 1
    rebuild_index: bool = False
    sample_dir: str | None = None  # opt-in validator sandbox; absolute server-FS path


class MapResponse(BaseModel):
    target_table: str
    specs: list[MappingSpec]
    classifications_summary: dict[str, int]
    validation_summary: dict[str, int] | None = None
    retry_count: int
    elapsed_sec: float


class EvalSummary(BaseModel):
    run_id: str
    pair: str
    provider: str
    model: str
    ran_at: datetime
    expected_count: int
    exact_match_rate_inclusive: float
    exact_match_rate_exclusive: float
    pipeline_dollars_total: float
    report_path: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    llm_provider: str
    llm_model: str
    embedder_provider: str
    embedder_model: str
    embedder_dims: int
    vector_db_exists: bool
    deep_check: dict[str, Any] | None = None
