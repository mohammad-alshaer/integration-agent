"""Decision playback trace — the full replay trail of one mapping's journey through the graph."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DecisionStep(BaseModel):
    step_name: str  # "schema_explorer.enrich", "semantic_matcher.rerank", ...
    agent: str  # "SchemaExplorer", "SemanticMatcher", ...
    input_ref: str  # key into a content-addressed blob store
    output_ref: str
    langfuse_trace_id: str | None = None
    started_at: datetime
    finished_at: datetime
    tokens_in: int = 0
    tokens_out: int = 0
    prompt_cache_hit: bool = False


class DecisionTrace(BaseModel):
    """Full replay trail for one mapping — rendered as the UI timeline in M4."""

    mapping_id: str
    steps: list[DecisionStep]
