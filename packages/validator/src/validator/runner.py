"""ValidationRunner — runs each MappingSpec's SQL against the sandbox, emits ValidationReport.

Strategy (single-source-table case):
  1. Resolve the single source table from spec.source_fqns.
  2. Wrap spec.sql (which is `SELECT <expr> AS <alias>`) as:
         SELECT <expr> AS <alias>
         FROM <sandbox_schema>.<schema>_<table>
         LIMIT <limit>
  3. Execute against the sandbox. Count rows and non-null results.

Strategy (multi-source-table case, M2.2+):
  Look up the FK relationship between the two source tables via ColumnProfile.fk_ref
  in the supplied SchemaProfile. Build an INNER JOIN with table-name aliases:
         SELECT <expr_with_table_prefixes> AS <alias>
         FROM <view_a> AS <table_a> INNER JOIN <view_b> AS <table_b>
              ON <table_a>.<fk_col> = <table_b>.<pk_col>
         LIMIT <limit>
  Restricted to 2-table joins; 3+ tables defer to later milestones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from schemas import (
    ColumnProfile,
    ErrorHint,
    ErrorKind,
    MappingSpec,
    SchemaProfile,
    ValidationReport,
)
from validator.error_hints import normalize_error
from validator.sandbox import Sandbox

log = logging.getLogger(__name__)

_DEFAULT_LIMIT = 100


@dataclass
class _FromClause:
    resolved: bool
    view: str | None
    note: str | None = None


def _columns_by_fqn(profile: SchemaProfile) -> dict[str, ColumnProfile]:
    return {c.fqn: c for tbl in profile.tables for c in tbl.columns}


def _find_fk_between(
    profile: SchemaProfile, table_a: tuple[str, str], table_b: tuple[str, str]
) -> tuple[str, str] | None:
    """Return (child_col, parent_col) for an FK linking table_a + table_b, or None.

    Scans ColumnProfile.fk_ref entries — one of the tables must have a column whose
    fk_ref points at a column in the other table. Returns (fk_column_in_child,
    pk_column_in_parent). Returns None if no FK is discoverable.
    """
    cols_by_fqn = _columns_by_fqn(profile)
    pair_a_str = f"{table_a[0]}.{table_a[1]}"
    pair_b_str = f"{table_b[0]}.{table_b[1]}"
    for col in cols_by_fqn.values():
        if not col.fk_ref:
            continue
        owner = (col.table_schema, col.table_name)
        ref_parts = col.fk_ref.rsplit(".", 1)
        if len(ref_parts) != 2:
            continue
        ref_table_str, ref_col = ref_parts
        # Match FK going either direction
        if owner == table_a and ref_table_str == pair_b_str:
            return (col.column_name, ref_col)
        if owner == table_b and ref_table_str == pair_a_str:
            return (col.column_name, ref_col)
    return None


def _resolve_from(
    spec: MappingSpec,
    sandbox: Sandbox,
    source_profile: SchemaProfile | None = None,
) -> _FromClause:
    """Resolve spec.source_fqns to a sandbox FROM clause (single view or JOIN)."""
    if not spec.source_fqns:
        return _FromClause(False, None, "spec has no source_fqns — nothing to validate")

    tables: set[tuple[str, str]] = set()
    for fqn in spec.source_fqns:
        parts = fqn.split(".")
        if len(parts) < 2:
            return _FromClause(False, None, f"malformed source_fqn {fqn!r}")
        tables.add((parts[0], parts[1]))

    if len(tables) == 1:
        (schema, table) = next(iter(tables))
        view = sandbox.view_for(schema, table)
        if view is None:
            return _FromClause(
                False,
                None,
                f"no Parquet sample loaded for {schema}.{table} "
                f"(did you run `worker profile --db ... --role source` with samples?)",
            )
        return _FromClause(True, view)

    if len(tables) == 2:
        if source_profile is None:
            return _FromClause(
                False,
                None,
                f"multi-table validation requires a source_profile to resolve FKs "
                f"(tables={sorted(tables)!r}); pass source_profile to ValidationRunner.",
            )
        sorted_tables = sorted(tables)
        ta, tb = sorted_tables[0], sorted_tables[1]
        view_a = sandbox.view_for(*ta)
        view_b = sandbox.view_for(*tb)
        if view_a is None or view_b is None:
            missing = ta if view_a is None else tb
            return _FromClause(
                False,
                None,
                f"no Parquet sample loaded for {missing[0]}.{missing[1]} "
                f"(needed for {sorted_tables!r} JOIN)",
            )
        fk = _find_fk_between(source_profile, ta, tb)
        if fk is None:
            return _FromClause(
                False,
                None,
                f"no FK relationship found between {ta[0]}.{ta[1]} and {tb[0]}.{tb[1]} "
                f"in the source profile; M2.2 only joins FK-linked tables.",
            )
        # Determine which side is the FK owner (child) — the side whose column carries fk_ref.
        cols_by_fqn = _columns_by_fqn(source_profile)
        candidate_a = cols_by_fqn.get(f"{ta[0]}.{ta[1]}.{fk[0]}")
        if candidate_a is not None and candidate_a.fk_ref and candidate_a.fk_ref.startswith(
            f"{tb[0]}.{tb[1]}."
        ):
            child_table, parent_table = ta, tb
            child_col, parent_col = fk
        else:
            child_table, parent_table = tb, ta
            child_col, parent_col = fk
        child_view = sandbox.view_for(*child_table)
        parent_view = sandbox.view_for(*parent_table)
        # Use bare table names as aliases — generator emits SQL referencing these
        join_clause = (
            f"{child_view} AS {child_table[1]} INNER JOIN {parent_view} AS {parent_table[1]} "
            f"ON {child_table[1]}.{child_col} = {parent_table[1]}.{parent_col}"
        )
        return _FromClause(True, join_clause)

    return _FromClause(
        False,
        None,
        f"3+ table sources not yet supported (tables={sorted(tables)!r}); defer to later milestone.",
    )


class ValidationRunner:
    """Runs MappingSpecs against a Sandbox; produces ValidationReports."""

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        row_limit: int = _DEFAULT_LIMIT,
        source_profile: SchemaProfile | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._row_limit = row_limit
        self._source_profile = source_profile

    def validate(self, spec: MappingSpec) -> ValidationReport:
        from_clause = _resolve_from(spec, self._sandbox, self._source_profile)
        if not from_clause.resolved:
            return ValidationReport(
                target_fqn=spec.target_fqn,
                passed=False,
                sample_rows_tested=0,
                sample_rows_passed=0,
                pass_rate=0.0,
                errors=[
                    ErrorHint(
                        kind=ErrorKind.OTHER,
                        offending_sql_snippet=spec.sql,
                        duckdb_error_message=from_clause.note or "unresolved FROM clause",
                        suggestion=from_clause.note,
                    )
                ],
            )

        # Determine the output alias (last segment of target_fqn) for NOT NULL counting
        alias = spec.target_fqn.split(".")[-1]
        query = f"{spec.sql} FROM {from_clause.view} LIMIT {self._row_limit}"

        try:
            rows = self._sandbox.con.execute(query).fetchall()
        except duckdb.Error as exc:
            hint = normalize_error(str(exc), sql_snippet=spec.sql)
            log.warning(
                "validator: %s failed (%s): %s",
                spec.target_fqn,
                hint.kind.value,
                str(exc).splitlines()[0] if str(exc) else "<no message>",
            )
            return ValidationReport(
                target_fqn=spec.target_fqn,
                passed=False,
                sample_rows_tested=0,
                sample_rows_passed=0,
                pass_rate=0.0,
                errors=[hint],
            )

        tested = len(rows)
        if tested == 0:
            # No samples loaded or empty table; treat as "can't validate" rather than fail
            return ValidationReport(
                target_fqn=spec.target_fqn,
                passed=False,
                sample_rows_tested=0,
                sample_rows_passed=0,
                pass_rate=0.0,
                errors=[
                    ErrorHint(
                        kind=ErrorKind.OTHER,
                        offending_sql_snippet=spec.sql,
                        duckdb_error_message="validation query returned 0 rows",
                        suggestion=(
                            "The sandbox has no rows in the source table. Re-run `worker profile "
                            "--include-samples` against a non-empty source, or reduce --row-limit."
                        ),
                    )
                ],
            )

        # Count passing rows. For M1 the only row-level assertion is: the computed output is
        # non-null. Target-NOT-NULL + accepted_values checks get layered on later.
        # Each row is a single-column tuple since spec.sql is `SELECT <expr> AS <alias>`.
        passed = sum(1 for r in rows if r[0] is not None)
        pass_rate = passed / tested if tested else 0.0

        errors: list[ErrorHint] = []
        if passed < tested:
            errors.append(
                ErrorHint(
                    kind=ErrorKind.NOT_NULL_VIOLATION,
                    offending_sql_snippet=spec.sql,
                    duckdb_error_message=(
                        f"{tested - passed}/{tested} rows produced NULL for output alias {alias!r}"
                    ),
                    suggestion=(
                        "The expression returns NULL for some rows. If the target is nullable, this "
                        "may be acceptable; if not, add COALESCE or handle the NULL inputs."
                    ),
                )
            )

        return ValidationReport(
            target_fqn=spec.target_fqn,
            passed=passed == tested,
            sample_rows_tested=tested,
            sample_rows_passed=passed,
            pass_rate=pass_rate,
            errors=errors,
        )


def validate_specs(
    specs: list[MappingSpec],
    sandbox: Sandbox,
    *,
    row_limit: int = _DEFAULT_LIMIT,
    source_profile: SchemaProfile | None = None,
) -> dict[str, ValidationReport]:
    """Convenience: validate a whole list, return dict by target_fqn. Also fills
    each spec's `validation_pass_rate` in place."""
    runner = ValidationRunner(sandbox, row_limit=row_limit, source_profile=source_profile)
    out: dict[str, ValidationReport] = {}
    for spec in specs:
        report = runner.validate(spec)
        out[spec.target_fqn] = report
        spec.validation_pass_rate = report.pass_rate
    return out
