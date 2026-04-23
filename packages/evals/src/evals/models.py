"""Eval artifacts — local to the evals package (not cross-specialist contracts)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from schemas import Pattern


class ExpectedMapping(BaseModel):
    target_fqn: str
    expected_pattern: Pattern
    expected_source_fqns: list[str]
    disputed: bool = False
    note: str | None = None


class ExpectedMappingsFile(BaseModel):
    pair: str
    source_database: str
    target_database: str
    mappings: list[ExpectedMapping]


class MatchLevel(StrEnum):
    EXACT = "exact"
    PATTERN = "pattern"
    SQL_SEMANTIC = "sql_semantic"
    MISMATCH = "mismatch"
    MISSING = "missing"
    EXTRA = "extra"


class ScoreEntry(BaseModel):
    target_fqn: str
    expected_pattern: Pattern | None
    actual_pattern: Pattern | None
    level: MatchLevel
    disputed: bool = False
    expected_source_fqns: list[str] = Field(default_factory=list)
    actual_source_fqns: list[str] = Field(default_factory=list)
    actual_sql: str | None = None
    actual_llm_confidence: float | None = None
    actual_validation_pass_rate: float | None = None


class EvalReport(BaseModel):
    pair: str
    provider: str
    model: str
    run_id: str
    ran_at: datetime
    expected_count: int
    actual_count: int
    exact_match_count: int
    pattern_match_count: int
    sql_semantic_match_count: int
    missing_count: int
    extra_count: int
    mismatch_count: int
    rates: dict[str, dict[str, float]]
    per_pattern: dict[str, dict[str, int]]
    mean_llm_confidence: float | None = None
    mean_validation_pass_rate: float | None = None
    prompt_cache_hit_rate: float | None = None
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    entries: list[ScoreEntry] = Field(default_factory=list)
