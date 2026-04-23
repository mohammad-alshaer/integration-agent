"""Transformation pattern taxonomy + classifier output."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Pattern(StrEnum):
    RENAME = "rename"  # 1:1
    CONCAT = "concat"  # N:1
    SPLIT = "split"  # 1:N
    DERIVED = "derived"  # computed
    CONSTANT = "constant"
    CONDITIONAL = "conditional"
    LOOKUP = "lookup"
    AGGREGATION = "aggregation"
    UNIT_CONVERSION = "unit_conversion"
    COMPOSITE = "composite"  # chain of the above
    UNSUPPORTED_IN_M1 = "unsupported_in_m1"  # classifier escape hatch


class PatternClassification(BaseModel):
    target_fqn: str
    pattern: Pattern
    source_fqns: list[str]
    rationale: str
    llm_confidence: float = Field(ge=0.0, le=1.0)  # self-report, NOT validation pass rate
