"""Normalize DuckDB error strings into structured ErrorHint objects.

The ErrorHint is the actual feedback loop into the Transformation Generator
on retry — clear ErrorKind + a natural-language suggestion lets the LLM fix
the specific issue rather than regenerate blindly.
"""

from __future__ import annotations

import re

from schemas import ErrorHint, ErrorKind

# Ordered: more specific patterns first.
_PATTERNS: list[tuple[re.Pattern[str], ErrorKind]] = [
    (
        re.compile(r'Binder Error.*Referenced column "(?P<col>[^"]+)" not found', re.IGNORECASE),
        ErrorKind.UNKNOWN_COLUMN,
    ),
    (re.compile(r"Binder Error.*column.*does not exist", re.IGNORECASE), ErrorKind.UNKNOWN_COLUMN),
    (
        re.compile(r"(Conversion Error|Cannot (implicitly )?cast)", re.IGNORECASE),
        ErrorKind.TYPE_MISMATCH,
    ),
    (
        re.compile(r"(NOT NULL constraint|null value in column)", re.IGNORECASE),
        ErrorKind.NOT_NULL_VIOLATION,
    ),
    (re.compile(r"(Parser Error|syntax error)", re.IGNORECASE), ErrorKind.PARSE_ERROR),
]


def _suggestion_for(kind: ErrorKind, match: re.Match[str] | None) -> str | None:
    if kind is ErrorKind.UNKNOWN_COLUMN:
        col = match.group("col") if match and "col" in (match.groupdict() or {}) else None
        if col:
            return (
                f"Column '{col}' does not exist in the source table. "
                f"Check the source column names and use only ones listed as SOURCES."
            )
        return "Reference columns by their exact source name. Check the SOURCES list."
    if kind is ErrorKind.TYPE_MISMATCH:
        return (
            "Add an explicit CAST so the expression's result type matches the target column's type. "
            "DuckDB did not find an implicit conversion."
        )
    if kind is ErrorKind.NOT_NULL_VIOLATION:
        return (
            "The target column is NOT NULL but the expression produced a NULL for at least one row. "
            "Use COALESCE, a non-null default, or handle the source-column NULLs explicitly."
        )
    if kind is ErrorKind.PARSE_ERROR:
        return (
            "The emitted SQL did not parse as DuckDB SQL. Return a plain expression (no SELECT/FROM), "
            "use balanced parens, and avoid dialect-specific syntax."
        )
    return None


def normalize_error(err_msg: str, sql_snippet: str = "") -> ErrorHint:
    """Map a raw DuckDB error string into an ErrorHint. Unknown patterns map to OTHER."""
    for pattern, kind in _PATTERNS:
        m = pattern.search(err_msg)
        if m:
            return ErrorHint(
                kind=kind,
                offending_sql_snippet=sql_snippet,
                duckdb_error_message=err_msg,
                suggestion=_suggestion_for(kind, m),
            )
    return ErrorHint(
        kind=ErrorKind.OTHER,
        offending_sql_snippet=sql_snippet,
        duckdb_error_message=err_msg,
        suggestion=None,
    )
