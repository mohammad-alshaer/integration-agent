"""ValidationRunner — runs each MappingSpec's SQL against the sandbox, emits ValidationReport.

Strategy (M1, single-source-table case):
  1. Resolve the single source table from spec.source_fqns.
  2. Wrap spec.sql (which is `SELECT <expr> AS <alias>`) as:
         SELECT <expr> AS <alias>
         FROM <sandbox_schema>.<schema>_<table>
         LIMIT <limit>
  3. Execute against the sandbox. Count rows and non-null results.

For multi-source-table cases the M1 validator emits a known-limitation
ValidationReport (passed=False, kind=OTHER, explicit suggestion). W2+ can
extend with FK-join resolution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from schemas import ErrorHint, ErrorKind, MappingSpec, ValidationReport
from validator.error_hints import normalize_error
from validator.sandbox import Sandbox

log = logging.getLogger(__name__)

_DEFAULT_LIMIT = 100


@dataclass
class _FromClause:
    resolved: bool
    view: str | None
    note: str | None = None


def _resolve_from(spec: MappingSpec, sandbox: Sandbox) -> _FromClause:
    """Resolve spec.source_fqns to a single sandbox view, or return a no-op reason."""
    if not spec.source_fqns:
        return _FromClause(False, None, "spec has no source_fqns — nothing to validate")

    tables: set[tuple[str, str]] = set()
    for fqn in spec.source_fqns:
        parts = fqn.split(".")
        if len(parts) < 2:
            return _FromClause(False, None, f"malformed source_fqn {fqn!r}")
        tables.add((parts[0], parts[1]))

    if len(tables) > 1:
        return _FromClause(
            False,
            None,
            f"multi-table sources not yet supported in the M1 validator "
            f"(tables={sorted(tables)!r}); mapping will need a JOIN-capable "
            f"validator in a later milestone.",
        )

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


class ValidationRunner:
    """Runs MappingSpecs against a Sandbox; produces ValidationReports."""

    def __init__(self, sandbox: Sandbox, *, row_limit: int = _DEFAULT_LIMIT) -> None:
        self._sandbox = sandbox
        self._row_limit = row_limit

    def validate(self, spec: MappingSpec) -> ValidationReport:
        from_clause = _resolve_from(spec, self._sandbox)
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
) -> dict[str, ValidationReport]:
    """Convenience: validate a whole list, return dict by target_fqn. Also fills
    each spec's `validation_pass_rate` in place."""
    runner = ValidationRunner(sandbox, row_limit=row_limit)
    out: dict[str, ValidationReport] = {}
    for spec in specs:
        report = runner.validate(spec)
        out[spec.target_fqn] = report
        spec.validation_pass_rate = report.pass_rate
    return out
