"""Unit tests for RenameGenerator."""

from __future__ import annotations

from generators import GenerationContext, RenameGenerator
from schemas import ColumnProfile, MappingProposal, Pattern


def _col(
    fqn: str, sql_type: str, *, is_nullable: bool = True, is_pk: bool = False
) -> ColumnProfile:
    schema, table, column = fqn.split(".", 2)
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=column,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=is_nullable,
        is_primary_key=is_pk,
        is_foreign_key=False,
        null_rate=0.0,
        distinct_count=1,
        total_count=1,
    )


class TestRenameTypeHandling:
    def test_identity_when_types_match(self) -> None:
        src = _col("Sales.Customer.CustomerID", "int")
        tgt = _col("dbo.DimCustomer.CustomerKey", "int", is_nullable=False, is_pk=True)
        proposal = MappingProposal(
            target_fqn=tgt.fqn,
            source_fqns=[src.fqn],
            pattern=Pattern.RENAME,
            rationale="business key rename",
        )
        spec = RenameGenerator().generate(proposal, GenerationContext(target=tgt, sources=[src]))

        assert spec.pattern == Pattern.RENAME
        assert spec.source_fqns == [src.fqn]
        assert "CustomerID AS CustomerKey" in spec.sql
        assert "CAST" not in spec.sql

    def test_cast_when_types_differ_translates_to_duckdb(self) -> None:
        src = _col("Sales.SalesOrderHeader.Status", "tinyint")
        tgt = _col("dbo.DimOrder.StatusCode", "nvarchar(10)")
        proposal = MappingProposal(
            target_fqn=tgt.fqn,
            source_fqns=[src.fqn],
            pattern=Pattern.RENAME,
            rationale="",
        )
        spec = RenameGenerator().generate(proposal, GenerationContext(target=tgt, sources=[src]))
        # SQL Server `nvarchar(10)` becomes DuckDB-compatible `VARCHAR(10)` so the
        # validator + dbt-duckdb don't reject the CAST.
        assert "CAST(Status AS VARCHAR(10))" in spec.sql
        assert "AS StatusCode" in spec.sql

    def test_money_target_emits_decimal_cast(self) -> None:
        """W4-E showed CAST(... AS money) errors; DuckDB has no MONEY type."""
        src = _col("Sales.SalesOrderDetail.LineTotal", "numeric(38,6)")
        tgt = _col("dbo.FactInternetSales.ExtendedAmount", "money")
        spec = RenameGenerator().generate(
            MappingProposal(
                target_fqn=tgt.fqn, source_fqns=[src.fqn], pattern=Pattern.RENAME, rationale=""
            ),
            GenerationContext(target=tgt, sources=[src]),
        )
        assert "CAST(LineTotal AS DECIMAL(19,4))" in spec.sql
        assert "money" not in spec.sql.lower()

    def test_nvarchar_size_change_still_compatible(self) -> None:
        """base_type strips size; nvarchar(50) -> nvarchar(100) should NOT CAST."""
        src = _col("Person.Person.FirstName", "nvarchar(50)")
        tgt = _col("dbo.DimCustomer.FirstName", "nvarchar(100)")
        proposal = MappingProposal(
            target_fqn=tgt.fqn, source_fqns=[src.fqn], pattern=Pattern.RENAME, rationale=""
        )
        spec = RenameGenerator().generate(proposal, GenerationContext(target=tgt, sources=[src]))
        assert "CAST" not in spec.sql
        assert "FirstName AS FirstName" in spec.sql


class TestRenameDbtTests:
    def test_not_null_added_when_target_required(self) -> None:
        src = _col("Sales.Customer.CustomerID", "int")
        tgt = _col("dbo.DimCustomer.CustomerKey", "int", is_nullable=False, is_pk=True)
        spec = RenameGenerator().generate(
            MappingProposal(
                target_fqn=tgt.fqn, source_fqns=[src.fqn], pattern=Pattern.RENAME, rationale=""
            ),
            GenerationContext(target=tgt, sources=[src]),
        )
        names = {t.name for t in spec.tests}
        assert "not_null" in names
        assert "unique" in names  # because is_pk=True

    def test_no_tests_when_nullable_non_pk(self) -> None:
        src = _col("Person.Person.MiddleName", "nvarchar(50)")
        tgt = _col("dbo.DimCustomer.MiddleName", "nvarchar(50)")
        spec = RenameGenerator().generate(
            MappingProposal(
                target_fqn=tgt.fqn, source_fqns=[src.fqn], pattern=Pattern.RENAME, rationale=""
            ),
            GenerationContext(target=tgt, sources=[src]),
        )
        assert spec.tests == []


class TestRenameMismatches:
    def test_raises_when_multiple_sources(self) -> None:
        import pytest

        src1 = _col("Person.Person.FirstName", "nvarchar(50)")
        src2 = _col("Person.Person.LastName", "nvarchar(50)")
        tgt = _col("dbo.DimCustomer.FullName", "nvarchar(100)")
        with pytest.raises(ValueError, match="exactly 1 source"):
            RenameGenerator().generate(
                MappingProposal(
                    target_fqn=tgt.fqn,
                    source_fqns=[src1.fqn, src2.fqn],
                    pattern=Pattern.RENAME,
                    rationale="",
                ),
                GenerationContext(target=tgt, sources=[src1, src2]),
            )
