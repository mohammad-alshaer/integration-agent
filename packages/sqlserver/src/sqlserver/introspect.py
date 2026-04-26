"""Introspect a SQL Server database into a raw SchemaProfile (no profile stats yet).

Reads:
  - INFORMATION_SCHEMA.TABLES        user tables (not views, not system)
  - INFORMATION_SCHEMA.COLUMNS       column metadata
  - INFORMATION_SCHEMA.KEY_COLUMN_USAGE + TABLE_CONSTRAINTS   PK/UQ detection
  - INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS + KEY_COLUMN_USAGE   FK graph
  - sys.extended_properties (MS_Description)   human-readable column / table docs
  - sys.computed_columns (definition)          T-SQL formula for computed columns

System schemas (sys, INFORMATION_SCHEMA) and the dbo.sysdiagrams noise table are filtered.

Profile stats (null_rate, distinct, top_values, min/max) are filled in by profile_stats.py —
running aggregate queries against the live database in one pass per table.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

import pyodbc

from schemas import ColumnProfile, SchemaProfile, TableProfile

log = logging.getLogger(__name__)

# Tables / schemas we always skip
_SKIP_SCHEMAS = frozenset({"sys", "INFORMATION_SCHEMA"})
_SKIP_TABLES = frozenset({("dbo", "sysdiagrams")})


def _user_tables(cur: pyodbc.Cursor) -> list[tuple[str, str]]:
    cur.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME "
        "FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME;"
    )
    tables: list[tuple[str, str]] = []
    for schema, name in cur.fetchall():
        if schema in _SKIP_SCHEMAS or (schema, name) in _SKIP_TABLES:
            continue
        tables.append((schema, name))
    return tables


def _columns_by_table(cur: pyodbc.Cursor) -> dict[tuple[str, str], list[dict]]:
    """Return {(schema, table): [raw column row, ...]} keyed by FQ table."""
    cur.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, "
        "       DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
        "       IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;"
    )
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in cur.fetchall():
        (s, t, c, pos, dtype, char_len, num_prec, num_scale, nullable) = row
        sql_type = _format_sql_type(dtype, char_len, num_prec, num_scale)
        out[(s, t)].append(
            {
                "column_name": c,
                "ordinal_position": pos,
                "sql_type": sql_type,
                "is_nullable": nullable == "YES",
            }
        )
    return out


def _format_sql_type(
    dtype: str, char_len: int | None, num_prec: int | None, num_scale: int | None
) -> str:
    """Compose e.g. `nvarchar(50)`, `decimal(18,4)`, `int`."""
    if dtype in ("char", "varchar", "nchar", "nvarchar", "binary", "varbinary"):
        if char_len is None:
            return dtype
        if char_len == -1:
            return f"{dtype}(max)"
        return f"{dtype}({char_len})"
    if dtype in ("decimal", "numeric") and num_prec is not None and num_scale is not None:
        return f"{dtype}({num_prec},{num_scale})"
    return dtype


def _primary_keys(cur: pyodbc.Cursor) -> dict[tuple[str, str], list[str]]:
    """FQ table -> ordered list of PK column names."""
    cur.execute(
        "SELECT kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.COLUMN_NAME, kcu.ORDINAL_POSITION "
        "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu "
        "JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc "
        "  ON kcu.CONSTRAINT_CATALOG = tc.CONSTRAINT_CATALOG "
        " AND kcu.CONSTRAINT_SCHEMA  = tc.CONSTRAINT_SCHEMA "
        " AND kcu.CONSTRAINT_NAME    = tc.CONSTRAINT_NAME "
        "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' "
        "ORDER BY kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.ORDINAL_POSITION;"
    )
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for schema, name, col, _pos in cur.fetchall():
        out[(schema, name)].append(col)
    return out


def _foreign_keys(cur: pyodbc.Cursor) -> dict[tuple[str, str], list[dict[str, str]]]:
    """FQ child-table -> list of {from: col, to: ref.table.col} FK edges."""
    cur.execute(
        """
        SELECT  fk_kcu.TABLE_SCHEMA  AS from_schema,
                fk_kcu.TABLE_NAME    AS from_table,
                fk_kcu.COLUMN_NAME   AS from_column,
                pk_kcu.TABLE_SCHEMA  AS to_schema,
                pk_kcu.TABLE_NAME    AS to_table,
                pk_kcu.COLUMN_NAME   AS to_column
        FROM    INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc
        JOIN    INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS fk_kcu
                ON rc.CONSTRAINT_NAME = fk_kcu.CONSTRAINT_NAME
        JOIN    INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS pk_kcu
                ON rc.UNIQUE_CONSTRAINT_NAME = pk_kcu.CONSTRAINT_NAME
               AND fk_kcu.ORDINAL_POSITION    = pk_kcu.ORDINAL_POSITION
        ORDER BY from_schema, from_table, fk_kcu.ORDINAL_POSITION;
        """
    )
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for fs, ft, fc, ts, tt, tc in cur.fetchall():
        out[(fs, ft)].append({"from": fc, "to": f"{ts}.{tt}.{tc}"})
    return out


def _column_descriptions(cur: pyodbc.Cursor) -> dict[tuple[str, str, str], str]:
    """(schema, table, column) -> MS_Description from sys.extended_properties."""
    cur.execute(
        """
        SELECT  sch.name AS table_schema,
                tab.name AS table_name,
                col.name AS column_name,
                CAST(ep.value AS NVARCHAR(MAX)) AS description
        FROM    sys.extended_properties ep
        JOIN    sys.tables   tab ON ep.major_id = tab.object_id
        JOIN    sys.schemas  sch ON tab.schema_id = sch.schema_id
        JOIN    sys.columns  col ON ep.major_id = col.object_id AND ep.minor_id = col.column_id
        WHERE   ep.name = 'MS_Description' AND ep.class = 1;
        """
    )
    return {(s, t, c): d for s, t, c, d in cur.fetchall()}


def _computed_definitions(cur: pyodbc.Cursor) -> dict[tuple[str, str, str], str]:
    """(schema, table, column) -> T-SQL `definition` from sys.computed_columns.

    Computed columns embed the underlying formula (e.g. LineTotal = UnitPrice * OrderQty);
    surfacing the definition lets downstream embedders see the formula text rather than
    just the column name. Failures here degrade gracefully — the introspector keeps
    working without computed-column enrichment.
    """
    try:
        cur.execute(
            """
            SELECT  sch.name AS table_schema,
                    tab.name AS table_name,
                    col.name AS column_name,
                    cc.definition AS definition
            FROM    sys.computed_columns cc
            JOIN    sys.tables   tab ON cc.object_id = tab.object_id
            JOIN    sys.schemas  sch ON tab.schema_id = sch.schema_id
            JOIN    sys.columns  col ON cc.object_id = col.object_id
                                    AND cc.column_id = col.column_id;
            """
        )
        return {(s, t, c): d for s, t, c, d in cur.fetchall() if d}
    except pyodbc.Error as exc:
        log.warning("introspect: sys.computed_columns query failed; continuing without enrichment: %s", exc)
        return {}


def _table_descriptions(cur: pyodbc.Cursor) -> dict[tuple[str, str], str]:
    """(schema, table) -> MS_Description from sys.extended_properties (minor_id=0)."""
    cur.execute(
        """
        SELECT  sch.name AS table_schema,
                tab.name AS table_name,
                CAST(ep.value AS NVARCHAR(MAX)) AS description
        FROM    sys.extended_properties ep
        JOIN    sys.tables   tab ON ep.major_id = tab.object_id
        JOIN    sys.schemas  sch ON tab.schema_id = sch.schema_id
        WHERE   ep.name = 'MS_Description' AND ep.class = 1 AND ep.minor_id = 0;
        """
    )
    return {(s, t): d for s, t, d in cur.fetchall()}


def _row_count_estimates(cur: pyodbc.Cursor) -> dict[tuple[str, str], int]:
    """Fast row count estimate via sys.dm_db_partition_stats (no table scan)."""
    cur.execute(
        """
        SELECT  sch.name                           AS table_schema,
                tab.name                           AS table_name,
                SUM(ps.row_count)                  AS est_row_count
        FROM    sys.dm_db_partition_stats ps
        JOIN    sys.tables   tab ON ps.object_id  = tab.object_id
        JOIN    sys.schemas  sch ON tab.schema_id = sch.schema_id
        WHERE   ps.index_id IN (0, 1)
        GROUP BY sch.name, tab.name;
        """
    )
    return {(s, t): int(n) for s, t, n in cur.fetchall()}


def introspect_schema(conn: pyodbc.Connection, database: str, *, role: str) -> SchemaProfile:
    """Introspect `database` into a SchemaProfile. No row-level profile stats yet."""
    cur = conn.cursor()

    tables = _user_tables(cur)
    columns_by = _columns_by_table(cur)
    pks = _primary_keys(cur)
    fks = _foreign_keys(cur)
    col_docs = _column_descriptions(cur)
    computed_defs = _computed_definitions(cur)
    tbl_docs = _table_descriptions(cur)
    row_est = _row_count_estimates(cur)

    # Index FK source columns for quick is_foreign_key / fk_ref lookup
    fk_col_index: dict[tuple[str, str, str], str] = {}
    for (schema, name), edges in fks.items():
        for edge in edges:
            fk_col_index[(schema, name, edge["from"])] = edge["to"]

    table_profiles: list[TableProfile] = []
    for schema, name in tables:
        pk_cols = pks.get((schema, name), [])
        column_profiles: list[ColumnProfile] = []
        for raw in columns_by.get((schema, name), []):
            col = raw["column_name"]
            column_profiles.append(
                ColumnProfile(
                    table_schema=schema,
                    table_name=name,
                    column_name=col,
                    ordinal_position=raw["ordinal_position"],
                    sql_type=raw["sql_type"],
                    is_nullable=raw["is_nullable"],
                    is_primary_key=col in pk_cols,
                    is_foreign_key=(schema, name, col) in fk_col_index,
                    fk_ref=fk_col_index.get((schema, name, col)),
                    ms_description=col_docs.get((schema, name, col)),
                    computed_definition=computed_defs.get((schema, name, col)),
                    # Profile stats filled by profile_tables(); zero placeholders:
                    null_rate=0.0,
                    distinct_count=0,
                    total_count=0,
                )
            )

        table_profiles.append(
            TableProfile(
                table_schema=schema,
                table_name=name,
                row_count_estimate=row_est.get((schema, name), 0),
                columns=column_profiles,
                primary_key=pk_cols,
                foreign_keys=fks.get((schema, name), []),
                ms_description=tbl_docs.get((schema, name)),
            )
        )

    return SchemaProfile(
        database_name=database,
        role=role,
        tables=table_profiles,
        profiled_at=datetime.now(UTC).isoformat(),
    )
