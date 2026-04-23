"""Unit tests for DuckDB error -> ErrorHint normalization."""

from __future__ import annotations

import pytest

from schemas import ErrorKind
from validator.error_hints import normalize_error


class TestNormalizeError:
    @pytest.mark.parametrize(
        ("err", "expected_kind"),
        [
            (
                'Binder Error: Referenced column "nonexistent_col" not found in FROM clause!',
                ErrorKind.UNKNOWN_COLUMN,
            ),
            (
                "Binder Error: Specified column does not exist",
                ErrorKind.UNKNOWN_COLUMN,
            ),
            (
                'Conversion Error: Could not convert string "foo" to INT32',
                ErrorKind.TYPE_MISMATCH,
            ),
            (
                "Cannot implicitly cast type VARCHAR to INTEGER",
                ErrorKind.TYPE_MISMATCH,
            ),
            (
                "Constraint Error: NOT NULL constraint failed on column target_col",
                ErrorKind.NOT_NULL_VIOLATION,
            ),
            (
                "null value in column target_col violates not-null constraint",
                ErrorKind.NOT_NULL_VIOLATION,
            ),
            (
                'Parser Error: syntax error at or near "SELCT"',
                ErrorKind.PARSE_ERROR,
            ),
            (
                "Some totally unknown runtime error we've never seen",
                ErrorKind.OTHER,
            ),
        ],
    )
    def test_kind_classification(self, err: str, expected_kind: ErrorKind) -> None:
        hint = normalize_error(err, sql_snippet="SELECT foo")
        assert hint.kind is expected_kind
        assert hint.duckdb_error_message == err
        assert hint.offending_sql_snippet == "SELECT foo"

    def test_unknown_column_suggestion_names_the_column(self) -> None:
        hint = normalize_error(
            'Binder Error: Referenced column "FirstNmae" not found in FROM clause!',
            sql_snippet="SELECT FirstNmae AS FirstName",
        )
        assert hint.kind is ErrorKind.UNKNOWN_COLUMN
        assert hint.suggestion is not None
        assert "'FirstNmae'" in hint.suggestion

    def test_other_has_no_suggestion(self) -> None:
        hint = normalize_error("??? weird error", sql_snippet="")
        assert hint.kind is ErrorKind.OTHER
        assert hint.suggestion is None

    def test_type_mismatch_suggests_cast(self) -> None:
        hint = normalize_error(
            "Conversion Error: type mismatch",
            sql_snippet="SELECT val",
        )
        assert hint.kind is ErrorKind.TYPE_MISMATCH
        assert hint.suggestion is not None
        assert "CAST" in hint.suggestion
