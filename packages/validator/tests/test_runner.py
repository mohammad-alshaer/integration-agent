"""Unit tests for ValidationRunner — end-to-end validation of MappingSpecs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from schemas import (
    ColumnProfile,
    ErrorKind,
    MappingSpec,
    Pattern,
    SchemaProfile,
    TableProfile,
)
from validator.runner import ValidationRunner, validate_specs
from validator.sandbox import Sandbox


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    pd.DataFrame(
        {
            "FirstName": ["Ada", None, "Grace", "Alan"],
            "LastName": ["Lovelace", "Hopper", "Hopper", "Turing"],
            "Age": [36, 85, 85, 41],
        }
    ).to_parquet(tmp_path / "Person.Person.parquet", index=False)
    return tmp_path


def _spec(
    target_fqn: str, source_fqns: list[str], sql: str, pattern: Pattern = Pattern.RENAME
) -> MappingSpec:
    return MappingSpec(
        target_fqn=target_fqn,
        source_fqns=source_fqns,
        pattern=pattern,
        sql=sql,
        rationale="test",
        tests=[],
        llm_confidence=0.0,
    )


class TestValidatorHappyPath:
    def test_all_rows_pass_for_simple_rename(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            runner = ValidationRunner(sb, row_limit=100)
            report = runner.validate(
                _spec(
                    "dbo.DimCustomer.LastName",
                    ["Person.Person.LastName"],
                    "SELECT LastName AS LastName",
                )
            )
            assert report.passed is True
            assert report.sample_rows_tested == 4
            assert report.sample_rows_passed == 4
            assert report.pass_rate == pytest.approx(1.0)
            assert report.errors == []

    def test_partial_pass_on_null_producing_rename(self, sample_dir: Path) -> None:
        # FirstName has one NULL row in the fixture
        with Sandbox(sample_dir) as sb:
            report = ValidationRunner(sb).validate(
                _spec(
                    "dbo.DimCustomer.FirstName",
                    ["Person.Person.FirstName"],
                    "SELECT FirstName AS FirstName",
                )
            )
            assert report.sample_rows_tested == 4
            assert report.sample_rows_passed == 3
            assert report.pass_rate == pytest.approx(0.75)
            assert report.passed is False
            # The runner emits a NOT_NULL-style hint on partial pass
            assert any(e.kind is ErrorKind.NOT_NULL_VIOLATION for e in report.errors)

    def test_concat_happy_path(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            report = ValidationRunner(sb).validate(
                _spec(
                    "dbo.DimCustomer.FullName",
                    ["Person.Person.FirstName", "Person.Person.LastName"],
                    "SELECT concat_ws(' ', FirstName, LastName) AS FullName",
                    pattern=Pattern.CONCAT,
                )
            )
            assert report.passed is True
            assert report.pass_rate == pytest.approx(1.0)


class TestValidatorCatchesErrors:
    def test_unknown_column_error(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            report = ValidationRunner(sb).validate(
                _spec(
                    "dbo.DimCustomer.Whoops",
                    ["Person.Person.FirstName"],
                    "SELECT nonexistent AS Whoops",
                )
            )
            assert report.passed is False
            assert report.errors, "should emit at least one error"
            assert report.errors[0].kind is ErrorKind.UNKNOWN_COLUMN

    def test_parse_error(self, sample_dir: Path) -> None:
        with Sandbox(sample_dir) as sb:
            report = ValidationRunner(sb).validate(
                _spec("dbo.DimCustomer.X", ["Person.Person.FirstName"], "SELCT FirstName AS X")
            )
            assert report.passed is False
            assert report.errors[0].kind is ErrorKind.PARSE_ERROR


class TestValidatorMultiTableWithoutProfile:
    def test_multi_source_tables_without_profile_emit_other_hint(self, sample_dir: Path) -> None:
        # Two sources across different tables, no source_profile -> can't resolve FK
        with Sandbox(sample_dir) as sb:
            report = ValidationRunner(sb).validate(
                _spec(
                    "dbo.X",
                    ["Person.Person.FirstName", "Sales.Customer.CustomerID"],
                    "SELECT FirstName AS X",
                )
            )
            assert report.passed is False
            assert report.errors[0].kind is ErrorKind.OTHER
            assert "source_profile" in (report.errors[0].duckdb_error_message or "")


def _col(
    *,
    schema: str,
    table: str,
    name: str,
    sql_type: str = "int",
    fk_ref: str | None = None,
) -> ColumnProfile:
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=name,
        ordinal_position=1,
        sql_type=sql_type,
        is_nullable=True,
        is_primary_key=False,
        is_foreign_key=fk_ref is not None,
        fk_ref=fk_ref,
        null_rate=0.0,
        distinct_count=0,
        total_count=0,
    )


def _profile_with_fk() -> SchemaProfile:
    """Two-table profile mirroring SalesOrderHeader -> SalesOrderDetail FK."""
    header_cols = [
        _col(schema="Sales", table="SalesOrderHeader", name="SalesOrderID"),
        _col(schema="Sales", table="SalesOrderHeader", name="TaxAmt", sql_type="money"),
        _col(schema="Sales", table="SalesOrderHeader", name="SubTotal", sql_type="money"),
    ]
    detail_cols = [
        _col(
            schema="Sales",
            table="SalesOrderDetail",
            name="SalesOrderID",
            fk_ref="Sales.SalesOrderHeader.SalesOrderID",
        ),
        _col(schema="Sales", table="SalesOrderDetail", name="LineTotal", sql_type="money"),
    ]
    return SchemaProfile(
        database_name="AdventureWorks2022",
        role="source",
        tables=[
            TableProfile(
                table_schema="Sales",
                table_name="SalesOrderHeader",
                row_count_estimate=0,
                columns=header_cols,
            ),
            TableProfile(
                table_schema="Sales",
                table_name="SalesOrderDetail",
                row_count_estimate=0,
                columns=detail_cols,
            ),
        ],
        profiled_at="2026-04-26T00:00:00+00:00",
    )


@pytest.fixture()
def join_sample_dir(tmp_path: Path) -> Path:
    """Two parquets with matching SalesOrderID FK linkage."""
    pd.DataFrame(
        {
            "SalesOrderID": [1, 2, 3],
            "TaxAmt": [10.0, 20.0, 30.0],
            "SubTotal": [100.0, 200.0, 300.0],
        }
    ).to_parquet(tmp_path / "Sales.SalesOrderHeader.parquet", index=False)
    pd.DataFrame(
        {
            "SalesOrderID": [1, 1, 2, 3],
            "LineTotal": [50.0, 50.0, 200.0, 300.0],
        }
    ).to_parquet(tmp_path / "Sales.SalesOrderDetail.parquet", index=False)
    return tmp_path


class TestValidatorMultiTableJoin:
    def test_multi_source_with_fk_succeeds(self, join_sample_dir: Path) -> None:
        # spec.sql uses table-name aliases (matching what the JOIN-aware generator emits)
        spec = _spec(
            "dbo.FactInternetSales.TaxAmt",
            [
                "Sales.SalesOrderHeader.TaxAmt",
                "Sales.SalesOrderHeader.SubTotal",
                "Sales.SalesOrderDetail.LineTotal",
            ],
            "SELECT SalesOrderHeader.TaxAmt * SalesOrderDetail.LineTotal "
            "/ SalesOrderHeader.SubTotal AS TaxAmt",
            pattern=Pattern.DERIVED,
        )
        with Sandbox(join_sample_dir) as sb:
            report = ValidationRunner(sb, source_profile=_profile_with_fk()).validate(spec)
        assert report.passed is True, f"expected pass; errors={report.errors}"
        assert report.sample_rows_tested == 4  # 4 detail rows after JOIN
        assert report.pass_rate == pytest.approx(1.0)

    def test_multi_source_without_fk_returns_error(self, tmp_path: Path) -> None:
        # Two tables both have parquet samples but the profile has no FK linking them
        pd.DataFrame({"FirstName": ["Ada"]}).to_parquet(
            tmp_path / "Person.Person.parquet", index=False
        )
        pd.DataFrame({"CustomerID": [1]}).to_parquet(
            tmp_path / "Sales.Customer.parquet", index=False
        )
        empty_profile = SchemaProfile(
            database_name="X",
            role="source",
            tables=[
                TableProfile(
                    table_schema="Person",
                    table_name="Person",
                    row_count_estimate=0,
                    columns=[_col(schema="Person", table="Person", name="FirstName")],
                ),
                TableProfile(
                    table_schema="Sales",
                    table_name="Customer",
                    row_count_estimate=0,
                    columns=[_col(schema="Sales", table="Customer", name="CustomerID")],
                ),
            ],
            profiled_at="2026-04-26T00:00:00+00:00",
        )
        with Sandbox(tmp_path) as sb:
            report = ValidationRunner(sb, source_profile=empty_profile).validate(
                _spec(
                    "dbo.X",
                    ["Person.Person.FirstName", "Sales.Customer.CustomerID"],
                    "SELECT FirstName AS X",
                )
            )
        assert report.passed is False
        assert report.errors[0].kind is ErrorKind.OTHER
        assert "FK relationship" in (report.errors[0].duckdb_error_message or "")


class TestValidateSpecsHelperFillsPassRate:
    def test_validate_specs_mutates_mapping_spec(self, sample_dir: Path) -> None:
        spec = _spec(
            "dbo.DimCustomer.LastName",
            ["Person.Person.LastName"],
            "SELECT LastName AS LastName",
        )
        assert spec.validation_pass_rate is None
        with Sandbox(sample_dir) as sb:
            reports = validate_specs([spec], sb)
        assert spec.validation_pass_rate == pytest.approx(1.0)
        assert reports[spec.target_fqn].passed is True
