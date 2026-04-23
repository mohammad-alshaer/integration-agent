"""Validator output: per-mapping pass rate + structured error hints fed back to the generator on retry."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ErrorKind(StrEnum):
    TYPE_MISMATCH = "type_mismatch"
    NOT_NULL_VIOLATION = "not_null_violation"
    PARSE_ERROR = "parse_error"
    UNKNOWN_COLUMN = "unknown_column"
    OTHER = "other"


class ErrorHint(BaseModel):
    """Structured hint fed back to the Generator on retry — never blind regeneration."""

    kind: ErrorKind
    offending_sql_snippet: str
    duckdb_error_message: str
    suggestion: str | None = None


class ValidationReport(BaseModel):
    target_fqn: str
    passed: bool
    sample_rows_tested: int
    sample_rows_passed: int
    pass_rate: float
    errors: list[ErrorHint] = []
