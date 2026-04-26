"""Pure parsing helpers shared between model.py and schema_yml.py.

The leading-underscore module name is the package-internal privacy boundary,
so the public-within-package functions here drop the `_` prefix.
"""

from __future__ import annotations

import re

from schemas import MappingSpec

_SELECT_RE = re.compile(r"^\s*SELECT\s+(?P<body>.+?)\s*$", re.DOTALL | re.IGNORECASE)


def split_select_expr(spec_sql: str) -> tuple[str, str] | None:
    """Parse `SELECT <expr> AS <alias>` into (expr, alias). Case-insensitive."""
    m = _SELECT_RE.match(spec_sql.strip())
    if not m:
        return None
    body = m.group("body").strip().rstrip(";")
    parts = re.split(r"\s+AS\s+", body, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    alias = parts[-1].strip().strip(",").strip()
    expr = " AS ".join(parts[:-1]).strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", alias):
        return None
    return expr, alias


def _snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def source_table_for(spec: MappingSpec) -> tuple[str, str] | None:
    """Unique (schema, table) across spec.source_fqns, or None if multi-table."""
    tables = source_tables_for(spec)
    return next(iter(tables)) if len(tables) == 1 else None


def source_tables_for(spec: MappingSpec) -> set[tuple[str, str]]:
    """Return the set of (schema, table) referenced by spec.source_fqns. Empty if malformed."""
    tables: set[tuple[str, str]] = set()
    for fqn in spec.source_fqns:
        parts = fqn.split(".")
        if len(parts) < 2:
            return set()
        tables.add((parts[0], parts[1]))
    return tables


def target_table_for(spec: MappingSpec) -> tuple[str, str]:
    parts = spec.target_fqn.split(".")
    if len(parts) < 3:
        raise ValueError(f"target_fqn {spec.target_fqn!r} must be schema.table.column")
    return parts[0], parts[1]


def target_column_for(spec: MappingSpec) -> str:
    """Bare target column name (last segment of target_fqn)."""
    return spec.target_fqn.rsplit(".", 1)[-1]


def model_name(target_schema: str, target_table: str, src_schema: str, src_table: str) -> str:
    return f"stg_{_snake(target_table)}_from_{_snake(src_schema)}_{_snake(src_table)}"


def intermediate_model_name(target_table: str, target_column: str) -> str:
    """e.g. ('FactInternetSales', 'TaxAmt') -> 'int_fact_internet_sales_tax_amt'."""
    return f"int_{_snake(target_table)}_{_snake(target_column)}"


__all__ = [
    "intermediate_model_name",
    "model_name",
    "source_table_for",
    "source_tables_for",
    "split_select_expr",
    "target_column_for",
    "target_table_for",
]
