"""Base protocol + helpers shared across pattern generators."""

from __future__ import annotations

from typing import ClassVar, Protocol

from pydantic import BaseModel

from schemas import ColumnProfile, DbtTest, ErrorHint, MappingProposal, MappingSpec, Pattern


class GenerationContext(BaseModel):
    """Resolved context for a generator — target and source ColumnProfiles by FQN."""

    model_config = {"arbitrary_types_allowed": True}

    target: ColumnProfile
    sources: list[ColumnProfile]  # ordered to match proposal.source_fqns
    # When non-empty, a previous attempt's validator feedback. Generators that emit
    # LLM-authored SQL (derived, future split/conditional/lookup) include these hints
    # in their retry prompt so the model can correct the specific failure. Deterministic
    # generators (rename, concat) ignore error_hints.
    error_hints: list[ErrorHint] = []


class PatternGenerator(Protocol):
    """Every generator implements this: classify-by-pattern + emit SQL + emit tests."""

    pattern: ClassVar[Pattern]

    def generate(self, proposal: MappingProposal, ctx: GenerationContext) -> MappingSpec: ...
    def test_assertions(self, spec: MappingSpec) -> list[DbtTest]: ...


# ---------- small SQL helpers reused by the concrete generators ----------


def column_alias(target_fqn: str) -> str:
    """Last segment of schema.table.column → column alias for the SELECT list."""
    return target_fqn.split(".")[-1]


def quote_col(source_fqn: str) -> str:
    """Quote just the column name from a FQN. Source tables are referenced via CTEs /
    the dbt `{{ source() }}` macro at the model layer, so we emit bare-column
    references here."""
    return source_fqn.split(".")[-1]


def base_type(sql_type: str) -> str:
    """Strip size suffix: `nvarchar(50)` -> `nvarchar`, `decimal(18,4)` -> `decimal`."""
    return sql_type.split("(")[0].strip().lower()


def types_compatible(a: str, b: str) -> bool:
    """Loose equivalence — same base type family. Enough to decide whether to CAST."""
    return base_type(a) == base_type(b)


# SQL Server -> DuckDB type translation. The validator runs against DuckDB so any
# SQL Server-only type names emitted in CAST(...) cause the validator to fail.
# Same mapping is reused for dbt-duckdb until M4+ swaps in dbt-sqlserver.
_SS_TO_DUCKDB_BASE: dict[str, str] = {
    "money": "DECIMAL(19,4)",
    "smallmoney": "DECIMAL(10,4)",
    "nvarchar": "VARCHAR",
    "nchar": "VARCHAR",
    "ntext": "VARCHAR",
    "varchar": "VARCHAR",
    "char": "VARCHAR",
    "text": "VARCHAR",
    "datetime2": "TIMESTAMP",
    "datetime": "TIMESTAMP",
    "smalldatetime": "TIMESTAMP",
    "datetimeoffset": "TIMESTAMP",
    "bit": "BOOLEAN",
    "uniqueidentifier": "UUID",
    "image": "BLOB",
    "varbinary": "BLOB",
    "binary": "BLOB",
    "xml": "VARCHAR",
    "hierarchyid": "VARCHAR",
    "geography": "VARCHAR",
    "geometry": "VARCHAR",
    "sql_variant": "VARCHAR",
    # Numeric + temporal that DuckDB already supports verbatim need no translation,
    # but we list them here so unknown types fall through to the original string.
    "decimal": "DECIMAL",
    "numeric": "DECIMAL",
    "int": "INTEGER",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "tinyint": "SMALLINT",
    "float": "DOUBLE",
    "real": "REAL",
    "date": "DATE",
    "time": "TIME",
    "boolean": "BOOLEAN",
}


def to_duckdb_type(sql_server_type: str) -> str:
    """Translate a SQL Server type spec to its DuckDB equivalent.

    Preserves precision/scale where the base type carries it (e.g.,
    `nvarchar(50)` -> `VARCHAR(50)`, `decimal(19,4)` -> `DECIMAL(19,4)`),
    drops it where DuckDB doesn't accept it (e.g., `datetime2(7)` -> `TIMESTAMP`).
    """
    raw = sql_server_type.strip()
    base = base_type(raw)
    mapped = _SS_TO_DUCKDB_BASE.get(base)
    if mapped is None:
        return raw  # unknown: pass through
    if "(" in raw and "(" not in mapped and mapped in {"VARCHAR", "DECIMAL"}:
        # Re-attach the size/precision tail when DuckDB accepts it
        tail = raw[raw.index("(") :]
        return f"{mapped}{tail}"
    return mapped


def default_tests_for_target(target: ColumnProfile) -> list[DbtTest]:
    """Default dbt assertions derivable from the target column metadata alone."""
    tests: list[DbtTest] = []
    if not target.is_nullable:
        tests.append(DbtTest(name="not_null"))
    if target.is_primary_key:
        tests.append(DbtTest(name="unique"))
    return tests
