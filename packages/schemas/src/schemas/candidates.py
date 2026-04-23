"""Source-field match candidates produced by the Semantic Matcher."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MatchCandidate(BaseModel):
    source_fqn: str
    embedding_similarity: float = Field(ge=-1.0, le=1.0)
    rationale: str


class CandidateSet(BaseModel):
    """Top-K ranked source candidates for a single target column."""

    target_fqn: str
    candidates: list[MatchCandidate]  # ordered best-first, len<=10
    no_match: bool = False
