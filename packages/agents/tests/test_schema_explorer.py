"""Schema Explorer tests — deterministic fold-back paths (no real LLM calls)."""

from __future__ import annotations

from typing import Any

from agents.schema_explorer import ColumnEnrichment, TableEnrichment, enrich_schema
from schemas import ColumnProfile, QualityFlag, SchemaProfile, SemanticType, TableProfile


class FakeLLM:
    """Drop-in LLMClient that returns a scripted TableEnrichment."""

    provider = "fake"
    model = "fake-1"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    def structured(self, system: str, user: str, schema: type) -> Any:  # noqa: ARG002
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _col(name: str, *, sql_type: str = "money", description: str | None = None) -> ColumnProfile:
    return ColumnProfile(
        table_schema="dbo",
        table_name="FactInternetSales",
        column_name=name,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=True,
        is_primary_key=False,
        is_foreign_key=False,
        ms_description=description,
        null_rate=0.0,
        distinct_count=0,
        total_count=0,
    )


def _profile(*cols: ColumnProfile) -> SchemaProfile:
    return SchemaProfile(
        database_name="AdventureWorksDW2022",
        role="target",
        tables=[
            TableProfile(
                table_schema="dbo",
                table_name="FactInternetSales",
                row_count_estimate=0,
                columns=list(cols),
            )
        ],
        profiled_at="2026-04-26T00:00:00+00:00",
    )


def test_enrich_fills_ms_description_when_empty() -> None:
    """Description-bare column gets ms_description from generated_description."""
    bare = _col("SalesAmount")
    profile = _profile(bare)
    llm = FakeLLM(
        [
            TableEnrichment(
                enrichments=[
                    ColumnEnrichment(
                        column_name="SalesAmount",
                        inferred_semantic_type=SemanticType.CURRENCY_AMOUNT,
                        semantic_type_confidence=0.9,
                        quality_flags=[QualityFlag.NO_DESCRIPTION],
                        generated_description="Total dollar amount of the sale per line item.",
                    )
                ]
            )
        ]
    )

    enrich_schema(profile, llm)

    out = profile.tables[0].columns[0]
    assert out.ms_description == "Total dollar amount of the sale per line item."
    assert out.inferred_semantic_type == SemanticType.CURRENCY_AMOUNT


def test_enrich_does_not_overwrite_existing_description() -> None:
    """If ms_description already populated, generated_description is ignored."""
    existing = _col("SalesAmount", description="Original description from sys.extended_properties.")
    profile = _profile(existing)
    llm = FakeLLM(
        [
            TableEnrichment(
                enrichments=[
                    ColumnEnrichment(
                        column_name="SalesAmount",
                        inferred_semantic_type=SemanticType.CURRENCY_AMOUNT,
                        semantic_type_confidence=0.9,
                        quality_flags=[],
                        generated_description="LLM hallucinated this — should be ignored.",
                    )
                ]
            )
        ]
    )

    enrich_schema(profile, llm)

    out = profile.tables[0].columns[0]
    assert out.ms_description == "Original description from sys.extended_properties."


def test_enrich_handles_null_generated_description() -> None:
    """Defaults are safe: a null generated_description leaves ms_description unchanged."""
    bare = _col("CustomerKey")
    profile = _profile(bare)
    llm = FakeLLM(
        [
            TableEnrichment(
                enrichments=[
                    ColumnEnrichment(
                        column_name="CustomerKey",
                        inferred_semantic_type=SemanticType.IDENTIFIER,
                        semantic_type_confidence=0.95,
                        quality_flags=[],
                        # generated_description omitted -> defaults to None
                    )
                ]
            )
        ]
    )

    enrich_schema(profile, llm)

    out = profile.tables[0].columns[0]
    assert out.ms_description is None
    assert out.inferred_semantic_type == SemanticType.IDENTIFIER
