"""Unit tests for Pattern Classifier deterministic paths (no real LLM calls)."""

from __future__ import annotations

from typing import Any

import pytest

from agents.pattern_classifier import ClassifierOutput, classify_target_columns
from schemas import CandidateSet, ColumnProfile, MatchCandidate, Pattern, SemanticType


def _target(
    fqn: str = "dbo.DimCustomer.FullName", sql_type: str = "nvarchar(100)"
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


class FakeLLM:
    """Drop-in LLMClient for tests. Returns a scripted ClassifierOutput or raises."""

    provider = "fake"
    model = "fake-1"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    def structured(self, system: str, user: str, schema: type) -> Any:  # noqa: ARG002
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestClassifierSkipsLLMWhenNoCandidates:
    def test_empty_candidate_set_returns_unsupported(self) -> None:
        target = _target()
        llm = FakeLLM([])  # no responses needed — classifier shouldn't call
        cs = {target.fqn: CandidateSet(target_fqn=target.fqn, candidates=[], no_match=True)}

        out = classify_target_columns([target], cs, llm)

        assert len(out) == 1
        pc = out[target.fqn]
        assert pc.pattern == Pattern.UNSUPPORTED_IN_M1
        assert pc.source_fqns == []
        assert "No candidate" in pc.rationale
        # LLM responses list unchanged -> no call made
        assert llm._responses == []

    def test_missing_candidate_set_returns_unsupported(self) -> None:
        target = _target()
        llm = FakeLLM([])
        out = classify_target_columns([target], {}, llm)
        assert out[target.fqn].pattern == Pattern.UNSUPPORTED_IN_M1


class TestClassifierValidatesSourceFqns:
    def test_drops_invented_source_fqns(self) -> None:
        target = _target()
        cs_one = CandidateSet(
            target_fqn=target.fqn,
            candidates=[
                MatchCandidate(
                    source_fqn="Person.Person.FirstName",
                    embedding_similarity=0.9,
                    rationale="name match",
                )
            ],
            no_match=False,
        )

        llm_response = ClassifierOutput(
            pattern=Pattern.RENAME,
            # LLM "hallucinates" an FQN not in the candidate set, plus a valid one:
            source_fqns=["Person.Person.FirstName", "SomeOther.Table.Col"],
            rationale="rename FirstName",
            llm_confidence=0.9,
        )
        llm = FakeLLM([llm_response])

        out = classify_target_columns([target], {target.fqn: cs_one}, llm)

        pc = out[target.fqn]
        assert pc.pattern == Pattern.RENAME
        assert pc.source_fqns == ["Person.Person.FirstName"]
        assert pc.llm_confidence == pytest.approx(0.9)


class TestClassifierHandlesLLMFailure:
    def test_llm_exception_falls_through_to_unsupported(self) -> None:
        target = _target()
        cs = {
            target.fqn: CandidateSet(
                target_fqn=target.fqn,
                candidates=[
                    MatchCandidate(
                        source_fqn="Person.Person.FirstName",
                        embedding_similarity=0.9,
                        rationale="name match",
                    )
                ],
                no_match=False,
            )
        }
        llm = FakeLLM([RuntimeError("model 503")])

        out = classify_target_columns([target], cs, llm)
        pc = out[target.fqn]
        assert pc.pattern == Pattern.UNSUPPORTED_IN_M1
        assert pc.llm_confidence == 0.0
        assert "Classifier LLM call failed" in pc.rationale


class TestClassifierUsesProfileMetadata:
    """Smoke: classifier includes target's semantic type in prompt when known."""

    def test_semantic_type_influences_prompt(self) -> None:
        target = _target()
        target.inferred_semantic_type = SemanticType.PERSON_NAME
        # We don't introspect the prompt here, just assert the happy path still works.
        cs = {
            target.fqn: CandidateSet(
                target_fqn=target.fqn,
                candidates=[
                    MatchCandidate(
                        source_fqn="Person.Person.FirstName",
                        embedding_similarity=0.9,
                        rationale="name",
                    )
                ],
                no_match=False,
            )
        }
        response = ClassifierOutput(
            pattern=Pattern.RENAME,
            source_fqns=["Person.Person.FirstName"],
            rationale="direct rename",
            llm_confidence=0.95,
        )
        out = classify_target_columns([target], cs, FakeLLM([response]))
        assert out[target.fqn].pattern == Pattern.RENAME
