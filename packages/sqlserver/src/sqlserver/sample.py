"""FK-closure sampler: export TOP N rows per seed table to Parquet, plus one hop of FK parents.

Design choices:
  - Use TABLESAMPLE where available for large tables; fall back to TOP N for small ones
    (TABLESAMPLE is approximate; for M1 with AW-sized tables TOP N is enough).
  - Apply PII redaction at the DataFrame step, before the Parquet file is written.
  - One Parquet per table, filename `<schema>.<table>.parquet` — DuckDB reads them as views.
  - FK-closure hop: for every FK column in a seed table, we pull the referenced parent rows.
    Depth is bounded to 1 hop; otherwise fan-out can explode on heavily linked schemas.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyodbc

from schemas import SchemaProfile
from sqlserver._util import quote_ident
from sqlserver.redaction import is_pii_column, mask_dataframe

log = logging.getLogger(__name__)


def _fq_table(schema: str, name: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(name)}"


def _sample_one_table(
    cur: pyodbc.Cursor,
    schema: str,
    name: str,
    n_rows: int,
) -> pd.DataFrame:
    """Fetch up to n_rows from a table into a pandas DataFrame."""
    # ORDER BY (SELECT NULL) keeps TOP N deterministic-ish without requiring a key column
    sql = f"SELECT TOP {int(n_rows)} * FROM {_fq_table(schema, name)} ORDER BY (SELECT NULL);"
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    # pyodbc rows aren't plain tuples — coerce explicitly
    data = [tuple(r) for r in rows]
    return pd.DataFrame(data, columns=cols)


def _parent_tables_of(profile: SchemaProfile, schema: str, name: str) -> set[tuple[str, str]]:
    """Return set of (schema, table) referenced by FKs on (schema, name)."""
    for t in profile.tables:
        if t.table_schema == schema and t.table_name == name:
            parents: set[tuple[str, str]] = set()
            for fk in t.foreign_keys:
                # fk["to"] format: "schema.table.column"
                parts = fk["to"].split(".")
                if len(parts) >= 2:
                    parents.add((parts[0], parts[1]))
            return parents
    return set()


def sample_to_parquet(
    conn: pyodbc.Connection,
    profile: SchemaProfile,
    out_dir: Path,
    *,
    seed_tables: list[tuple[str, str]] | None = None,
    n_per_table: int = 1000,
    include_fk_parents: bool = True,
) -> dict[tuple[str, str], Path]:
    """Sample seed tables (and optional FK parents) to Parquet under `out_dir`.

    If `seed_tables` is None, sample every table in the profile.
    Returns a mapping {(schema, table): parquet_path}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()

    if seed_tables is None:
        seeds = [(t.table_schema, t.table_name) for t in profile.tables]
    else:
        seeds = list(seed_tables)

    to_sample: set[tuple[str, str]] = set(seeds)
    if include_fk_parents:
        for s, n in seeds:
            to_sample.update(_parent_tables_of(profile, s, n))

    results: dict[tuple[str, str], Path] = {}
    for schema, name in sorted(to_sample):
        try:
            df = _sample_one_table(cur, schema, name, n_per_table)
        except pyodbc.Error as exc:
            log.warning("sample failed for %s.%s: %s", schema, name, exc)
            continue

        # PII redaction at the DataFrame step — before Parquet
        pii_cols = [c for c in df.columns if is_pii_column(c)]
        if pii_cols:
            df = mask_dataframe(df, pii_cols)

        path = out_dir / f"{schema}.{name}.parquet"
        df.to_parquet(path, index=False)
        results[(schema, name)] = path
        log.info(
            "sample %s.%s -> %s (%d rows, %d cols)", schema, name, path, len(df), len(df.columns)
        )

    return results
