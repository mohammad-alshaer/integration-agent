"""Unit tests for ValidationRunner — end-to-end validation of MappingSpecs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from schemas import ErrorKind, MappingSpec, Pattern
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


class TestValidatorMultiTableLimitation:
    def test_multi_source_tables_emit_other_hint(self, sample_dir: Path) -> None:
        # Two sources across different tables
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
            assert "multi-table" in (report.errors[0].duckdb_error_message or "").lower()


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
