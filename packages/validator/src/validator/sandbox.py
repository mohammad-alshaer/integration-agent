"""In-memory DuckDB sandbox that loads Parquet samples as views.

Each Parquet file under `sample_dir` is named `<schema>.<table>.parquet`
(as written by `sqlserver.sample.sample_to_parquet`). We load each as a
VIEW at `<sandbox_schema>.<schema>_<table>` — underscore-joined because
DuckDB treats `foo.bar` as "table `bar` in schema `foo`", and we want the
whole source-table identity in a single identifier.

The sandbox is disposable — a fresh :memory: DuckDB per graph run. No
state leaks between runs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)


class Sandbox:
    """Session-scoped DuckDB sandbox over the Parquet-exported source samples.

    By default the sandbox is in-memory. Pass `db_path` to persist the views to
    a file so other processes (notably dbt-duckdb) can connect to the same state.
    """

    def __init__(
        self,
        sample_dir: Path,
        *,
        sandbox_schema: str = "source_raw",
        db_path: Path | None = None,
    ) -> None:
        self._sample_dir = sample_dir
        self._schema = sandbox_schema
        self._db_path = db_path
        target = ":memory:" if db_path is None else str(db_path)
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(target)
        self._con.execute(f"CREATE SCHEMA IF NOT EXISTS {sandbox_schema}")
        self._loaded: dict[tuple[str, str], str] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._sample_dir.exists():
            log.warning("sandbox: sample_dir %s does not exist — no views loaded", self._sample_dir)
            return
        for pq in sorted(self._sample_dir.glob("*.parquet")):
            stem = pq.stem
            parts = stem.split(".", 1)
            if len(parts) != 2:
                log.warning("sandbox: skipping %s (expected <schema>.<table>.parquet)", pq.name)
                continue
            schema_part, table_part = parts
            view_name = f"{self._schema}.{schema_part}_{table_part}"
            # DuckDB does not support parameterized CREATE VIEW; escape single quotes
            # in the path and inline. Backslashes are fine inside DuckDB single-quoted literals.
            path_lit = str(pq).replace("'", "''")
            self._con.execute(
                f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_parquet('{path_lit}')"
            )
            self._loaded[(schema_part, table_part)] = view_name
        log.info("sandbox: loaded %d source views from %s", len(self._loaded), self._sample_dir)

    def view_for(self, schema: str, table: str) -> str | None:
        """Return the fully-qualified sandbox view name for a source table, or None."""
        return self._loaded.get((schema, table))

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        return self._con

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
