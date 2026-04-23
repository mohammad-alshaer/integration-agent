"""Fill in per-column profile stats (null_rate, distinct_count, total_count, top_values, min/max).

Runs SQL aggregates against SQL Server directly — much faster than pulling samples first.
One round-trip per table rather than per column.
"""

from __future__ import annotations

import logging

import pyodbc

from schemas import ColumnProfile, SchemaProfile, TableProfile
from sqlserver._util import quote_ident

log = logging.getLogger(__name__)

# SQL Server types that support MIN/MAX directly
_MIN_MAX_TYPES = frozenset(
    {
        "int",
        "bigint",
        "smallint",
        "tinyint",
        "decimal",
        "numeric",
        "float",
        "real",
        "money",
        "smallmoney",
        "date",
        "datetime",
        "datetime2",
        "smalldatetime",
        "datetimeoffset",
        "time",
    }
)

# Types where top_values + MIN/MAX make sense and aren't huge
_TOP_VALUES_TYPES = frozenset(
    {
        "int",
        "bigint",
        "smallint",
        "tinyint",
        "char",
        "varchar",
        "nchar",
        "nvarchar",
        "bit",
        "date",
        "datetime",
        "datetime2",
        "smalldatetime",
    }
)

# Types we skip entirely for profile stats (expensive or opaque)
_SKIP_TYPES = frozenset({"image", "text", "ntext", "xml", "hierarchyid", "geography", "geometry"})


def _base_type(sql_type: str) -> str:
    """Strip size suffix: `nvarchar(50)` -> `nvarchar`."""
    return sql_type.split("(")[0].strip()


def _profile_table(cur: pyodbc.Cursor, table: TableProfile) -> None:
    """In-place: fill total_count, null_rate, distinct_count, top_values, min/max on each column."""
    schema = quote_ident(table.table_schema)
    name = quote_ident(table.table_name)
    fq = f"{schema}.{name}"

    # 1) Total row count (exact, for the single-pass aggregates below)
    cur.execute(f"SELECT COUNT_BIG(*) FROM {fq};")
    total = int(cur.fetchone()[0])

    # 2) Per-column: NULL count + distinct count + min/max in ONE pass per table
    #    Build a big SELECT with one set of aggregates per column.
    aggs: list[str] = []
    aggs_cols: list[ColumnProfile] = []
    for col in table.columns:
        bt = _base_type(col.sql_type)
        if bt in _SKIP_TYPES:
            continue
        qc = quote_ident(col.column_name)
        aggs.append(f"SUM(CASE WHEN {qc} IS NULL THEN 1 ELSE 0 END)")
        if bt in _MIN_MAX_TYPES:
            aggs.append(f"MIN({qc})")
            aggs.append(f"MAX({qc})")
        else:
            aggs.append("CAST(NULL AS SQL_VARIANT)")
            aggs.append("CAST(NULL AS SQL_VARIANT)")
        # distinct count via COUNT(DISTINCT) — can be slow on huge tables but AW is small
        aggs.append(f"COUNT(DISTINCT {qc})")
        aggs_cols.append(col)

    if not aggs:
        # Nothing profileable; just stamp total_count everywhere we can
        for col in table.columns:
            col.total_count = total
        return

    cur.execute(f"SELECT {', '.join(aggs)} FROM {fq};")
    row = cur.fetchone()

    i = 0
    for col in aggs_cols:
        null_ct = int(row[i] or 0)
        minv = row[i + 1]
        maxv = row[i + 2]
        distinct = int(row[i + 3] or 0)
        i += 4

        col.total_count = total
        col.null_rate = (null_ct / total) if total else 0.0
        col.distinct_count = distinct
        col.min_value = minv
        col.max_value = maxv

    # Also stamp total_count on skipped columns
    for col in table.columns:
        if col.total_count == 0 and total:
            col.total_count = total

    # 3) Top values: per-column TOP 5. Only run if table is small (<100k rows)
    #    and column type is appropriate. Skip otherwise — not worth the cost for M1.
    if total > 100_000:
        return
    for col in table.columns:
        bt = _base_type(col.sql_type)
        if bt not in _TOP_VALUES_TYPES:
            continue
        if col.distinct_count <= 0:
            continue
        qc = quote_ident(col.column_name)
        try:
            cur.execute(
                f"SELECT TOP 5 {qc}, COUNT(*) AS n "
                f"FROM {fq} "
                f"WHERE {qc} IS NOT NULL "
                f"GROUP BY {qc} "
                f"ORDER BY COUNT(*) DESC;"
            )
            col.top_values = [(v, int(n)) for v, n in cur.fetchall()]
        except pyodbc.Error as exc:
            log.warning("top_values failed for %s.%s: %s", table.table_name, col.column_name, exc)


def profile_tables(conn: pyodbc.Connection, profile: SchemaProfile) -> SchemaProfile:
    """Fill in profile stats across all tables in `profile`. Mutates + returns the profile."""
    cur = conn.cursor()
    n = len(profile.tables)
    for idx, table in enumerate(profile.tables, 1):
        log.info("profile_stats %d/%d: %s.%s", idx, n, table.table_schema, table.table_name)
        _profile_table(cur, table)
    return profile
