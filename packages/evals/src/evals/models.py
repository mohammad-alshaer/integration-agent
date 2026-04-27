"""Eval artifacts — local to the evals package (not cross-specialist contracts)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from schemas import Pattern


class ExpectedAlternative(BaseModel):
    """A semantically-equivalent alternative form a model may legitimately emit.

    Stylistic alternatives in schema mapping (e.g. `RENAME [LineTotal]` vs
    `DERIVED [UnitPrice, OrderQty]`) are both correct in production. Listing them
    here lets the scorer credit either form as EXACT. `reason` is required so
    every alternative is justified at review time — mitigates rubber-stamping.
    """

    pattern: Pattern
    source_fqns: list[str]
    reason: str


class ExpectedMapping(BaseModel):
    target_fqn: str
    expected_pattern: Pattern
    expected_source_fqns: list[str]
    disputed: bool = False
    note: str | None = None
    accepted_alternatives: list[ExpectedAlternative] = Field(default_factory=list)

    @field_validator("accepted_alternatives")
    @classmethod
    def _max_two_alternatives(
        cls, v: list[ExpectedAlternative]
    ) -> list[ExpectedAlternative]:
        if len(v) > 2:
            raise ValueError(
                "max 2 accepted_alternatives per spec; gate against scorer rubber-stamping"
            )
        return v


class ExpectedMappingsFile(BaseModel):
    pair: str
    source_database: str
    target_database: str
    mappings: list[ExpectedMapping]


class MatchLevel(StrEnum):
    EXACT = "exact"
    PATTERN = "pattern"
    SQL_EXEC_EQUIVALENT = "sql_exec_equivalent"
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
    sql_exec_equivalent_match_count: int = 0
    sql_semantic_match_count: int
    missing_count: int
    extra_count: int
    mismatch_count: int
    rates: dict[str, dict[str, float]]
    per_pattern: dict[str, dict[str, int]]
    mean_llm_confidence: float | None = None
    mean_validation_pass_rate: float | None = None
    prompt_cache_hit_rate: float | None = None
    # Per-spec aggregates: sum across MappingSpecs (generator-only — Rename/Concat
    # don't make LLM calls, so these reflect DERIVED-generator usage).
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    # Pipeline-wide aggregates from LLMClient running totals: matcher + classifier
    # + generator + retries. The honest full-run cost number.
    pipeline_total_llm_calls: int = 0
    pipeline_total_tokens_in: int = 0
    pipeline_total_tokens_out: int = 0
    pipeline_cache_hit_rate: float | None = None
    # M2.7: token totals × per-provider pricing. See evals/pricing.py.
    pipeline_dollars_in: float = 0.0
    pipeline_dollars_out: float = 0.0
    pipeline_dollars_total: float = 0.0
    entries: list[ScoreEntry] = Field(default_factory=list)
