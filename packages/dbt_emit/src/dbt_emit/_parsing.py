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
    tables: set[tuple[str, str]] = set()
    for fqn in spec.source_fqns:
        parts = fqn.split(".")
        if len(parts) < 2:
            return None
        tables.add((parts[0], parts[1]))
    return tables.pop() if len(tables) == 1 else None


def target_table_for(spec: MappingSpec) -> tuple[str, str]:
    parts = spec.target_fqn.split(".")
    if len(parts) < 3:
        raise ValueError(f"target_fqn {spec.target_fqn!r} must be schema.table.column")
    return parts[0], parts[1]


def model_name(target_schema: str, target_table: str, src_schema: str, src_table: str) -> str:
    return f"stg_{_snake(target_table)}_from_{_snake(src_schema)}_{_snake(src_table)}"


__all__ = [
    "model_name",
    "source_table_for",
    "split_select_expr",
    "target_table_for",
]
