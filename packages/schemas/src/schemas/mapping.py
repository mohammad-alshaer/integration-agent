"""Mapping proposals (input to generators) + specs (persisted artifact)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.patterns import Pattern


class MappingProposal(BaseModel):
    """Input to a pattern generator."""

    target_fqn: str
    source_fqns: list[str]
    pattern: Pattern
    rationale: str


class DbtTest(BaseModel):
    """A single schema.yml-compatible test assertion."""

    name: str  # "not_null", "unique", "accepted_values", ...
    config: dict = {}


class MappingSpec(BaseModel):
    """Output of a pattern generator. This is the persisted artifact."""

    target_fqn: str
    source_fqns: list[str]
    pattern: Pattern
    sql: str  # dbt-compatible SELECT expression
    rationale: str
    tests: list[DbtTest]

    # Confidences — REPORTED, never merged:
    llm_confidence: float = Field(ge=0.0, le=1.0)  # model self-report
    validation_pass_rate: float | None = None  # filled in by Validator

    # Generation metadata
    provider: str = "gemini"
    model: str = "gemini-2.5-pro"
    prompt_cache_hit: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
