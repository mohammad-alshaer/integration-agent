"""Unit tests for DerivedGenerator with a scripted FakeLLM."""

from __future__ import annotations

from typing import Any

from generators import DerivedGenerator, GenerationContext
from generators.derived import DerivedSpec
from schemas import ColumnProfile, MappingProposal, Pattern


def _col(
    fqn: str, sql_type: str, *, desc: str | None = None, is_nullable: bool = True
) -> ColumnProfile:
    schema, table, column = fqn.split(".", 2)
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=column,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=is_nullable,
        is_primary_key=False,
        is_foreign_key=False,
        ms_description=desc,
        null_rate=0.0,
        distinct_count=1,
        total_count=1,
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


class TestDerivedExpression:
    def test_case_statement_attaches_accepted_values_test(self) -> None:
        src = _col("Person.Person.EmailPromotion", "int")
        tgt = _col("dbo.DimCustomer.EmailPromotionCategory", "nvarchar(40)")

        response = DerivedSpec(
            sql_expression=(
                "CASE WHEN EmailPromotion = 0 THEN 'None' "
                "WHEN EmailPromotion = 1 THEN 'AdventureWorks Only' "
                "WHEN EmailPromotion = 2 THEN 'AdventureWorks and Partners' END"
            ),
            rationale="integer-coded enum -> human label",
            accepted_values=["None", "AdventureWorks Only", "AdventureWorks and Partners"],
            confidence=0.9,
        )

        spec = DerivedGenerator(FakeLLM([response])).generate(
            MappingProposal(
                target_fqn=tgt.fqn,
                source_fqns=[src.fqn],
                pattern=Pattern.DERIVED,
                rationale="",
            ),
            GenerationContext(target=tgt, sources=[src]),
        )

        assert spec.pattern == Pattern.DERIVED
        assert "AS EmailPromotionCategory" in spec.sql
        assert "CASE WHEN EmailPromotion" in spec.sql
        # accepted_values test emitted
        av_tests = [t for t in spec.tests if t.name == "accepted_values"]
        assert len(av_tests) == 1
        assert av_tests[0].config["values"] == [
            "None",
            "AdventureWorks Only",
            "AdventureWorks and Partners",
        ]
        assert spec.llm_confidence == 0.9


class TestDerivedFallback:
    def test_llm_failure_falls_through_to_passthrough_cast(self) -> None:
        src = _col("t.t.src_col", "int")
        tgt = _col("u.u.tgt_col", "varchar(50)")
        spec = DerivedGenerator(FakeLLM([RuntimeError("503")])).generate(
            MappingProposal(
                target_fqn=tgt.fqn,
                source_fqns=[src.fqn],
                pattern=Pattern.DERIVED,
                rationale="",
            ),
            GenerationContext(target=tgt, sources=[src]),
        )
        assert "CAST(src_col AS varchar(50))" in spec.sql
        assert spec.llm_confidence == 0.0
        assert "fallback" in spec.rationale.lower() or "failed" in spec.rationale.lower()


class TestDerivedArithmetic:
    def test_sum_of_money_columns(self) -> None:
        sub = _col("Sales.SalesOrderHeader.SubTotal", "money")
        tax = _col("Sales.SalesOrderHeader.TaxAmt", "money")
        frt = _col("Sales.SalesOrderHeader.Freight", "money")
        tgt = _col("dbo.FactInternetSales.SalesAmount", "money", is_nullable=False)

        response = DerivedSpec(
            sql_expression="SubTotal + TaxAmt + Freight",
            rationale="Total sales = SubTotal + Tax + Freight",
            accepted_values=None,
            confidence=0.95,
        )
        spec = DerivedGenerator(FakeLLM([response])).generate(
            MappingProposal(
                target_fqn=tgt.fqn,
                source_fqns=[sub.fqn, tax.fqn, frt.fqn],
                pattern=Pattern.DERIVED,
                rationale="",
            ),
            GenerationContext(target=tgt, sources=[sub, tax, frt]),
        )
        assert "SubTotal + TaxAmt + Freight" in spec.sql
        assert "AS SalesAmount" in spec.sql
        # No accepted_values test when the response didn't provide one
        assert not [t for t in spec.tests if t.name == "accepted_values"]
