"""Unit tests for Semantic Matcher — tests the non-LLM paths and hallucination filtering."""

from __future__ import annotations

from typing import Any

from agents.semantic_matcher import (
    MatcherOutput,
    RerankedCandidate,
    _embedding_only_candidate_set,
    _match_one,
)
from agents.vector_store import Neighbor
from schemas import ColumnProfile


def _target(
    fqn: str = "dbo.DimCustomer.FirstName", sql_type: str = "nvarchar(50)"
) -> ColumnProfile:
    schema, table, column = fqn.split(".", 2)
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=column,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=True,
        is_primary_key=False,
        is_foreign_key=False,
        null_rate=0.0,
        distinct_count=1,
        total_count=1,
    )


def _nb(fqn: str, sql_type: str = "nvarchar(50)", d: float = 0.5) -> Neighbor:
    return Neighbor(
        fqn=fqn, sql_type=sql_type, ms_description=None, top_values_text=None, distance=d
    )


class FakeLLM:
    provider = "fake"
    model = "fake-1"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    def structured(self, system: str, user: str, schema: type) -> Any:  # noqa: ARG002
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestEmbeddingOnlyFallback:
    def test_fallback_builds_candidate_set_from_neighbors(self) -> None:
        neighbors = [_nb("a.b.col1", d=0.2), _nb("a.b.col2", d=0.4), _nb("a.b.col3", d=0.9)]
        cs = _embedding_only_candidate_set("t.t.target", neighbors)
        assert cs.target_fqn == "t.t.target"
        assert [c.source_fqn for c in cs.candidates] == ["a.b.col1", "a.b.col2", "a.b.col3"]
        # similarity is max(0, 1 - distance)
        assert cs.candidates[0].embedding_similarity > cs.candidates[-1].embedding_similarity
        assert all("fallback" in c.rationale.lower() for c in cs.candidates)
        assert cs.no_match is False


class TestMatchOneDropsHallucinatedFqns:
    def test_invented_source_fqn_is_dropped(self) -> None:
        target = _target()
        neighbors = [_nb("Person.Person.FirstName"), _nb("Person.Person.LastName")]
        llm_response = MatcherOutput(
            candidates=[
                RerankedCandidate(
                    source_fqn="Person.Person.FirstName",
                    rationale="name",
                    similarity=0.95,
                ),
                RerankedCandidate(
                    source_fqn="Totally.Fake.Column",  # hallucinated
                    rationale="nope",
                    similarity=0.9,
                ),
            ],
            no_match=False,
        )
        out: dict = {}
        _match_one(target, neighbors, FakeLLM([llm_response]), out)

        cs = out[target.fqn]
        assert [c.source_fqn for c in cs.candidates] == ["Person.Person.FirstName"]

    def test_all_hallucinated_sets_no_match(self) -> None:
        target = _target()
        neighbors = [_nb("Person.Person.FirstName")]
        llm_response = MatcherOutput(
            candidates=[
                RerankedCandidate(source_fqn="Ghost.Ghost.Ghost", rationale="nope", similarity=0.5)
            ],
            no_match=False,
        )
        out: dict = {}
        _match_one(target, neighbors, FakeLLM([llm_response]), out)

        cs = out[target.fqn]
        assert cs.no_match is True
        assert cs.candidates == []


class TestMatchOneHandlesLLMFailure:
    def test_exception_triggers_embedding_only_fallback(self) -> None:
        target = _target()
        neighbors = [_nb("Person.Person.FirstName", d=0.2)]
        out: dict = {}
        _match_one(target, neighbors, FakeLLM([RuntimeError("503")]), out)

        cs = out[target.fqn]
        assert cs.candidates, "fallback should produce at least one candidate"
        assert "fallback" in cs.candidates[0].rationale.lower()


class TestMatchOneEmptyNeighbors:
    def test_no_neighbors_returns_no_match_without_calling_llm(self) -> None:
        target = _target()
        llm = FakeLLM([])  # empty — classifier should NOT call
        out: dict = {}
        _match_one(target, [], llm, out)

        cs = out[target.fqn]
        assert cs.no_match is True
        assert cs.candidates == []
