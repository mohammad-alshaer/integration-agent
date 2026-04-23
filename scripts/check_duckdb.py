"""Smoke test: create DuckDB file, load vss extension, run a toy HNSW query.

This verifies the full stack we need for metadata + vector search:
  - DuckDB can create a persistent file
  - The `vss` extension downloads and loads (DuckDB's extension repo)
  - HNSW index builds and array_distance queries return correct order

Since Docker/WSL/Podman are blocked on this machine, DuckDB + vss is our
unified metadata + vector store (replaces Postgres+pgvector from the plan).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_DIR = Path(".duckdb")
DB_FILE = DB_DIR / "integration_agent.duckdb"


def main() -> int:
    DB_DIR.mkdir(exist_ok=True)

    con = duckdb.connect(str(DB_FILE))
    try:
        print(f"DuckDB version: {duckdb.__version__}")
        print(f"DB file: {DB_FILE.resolve()}")

        con.execute("INSTALL vss")
        con.execute("LOAD vss")
        print("vss extension loaded.")

        # Clean slate each run for this smoke test
        con.execute("DROP TABLE IF EXISTS toy_vectors")
        con.execute("CREATE TABLE toy_vectors (id INT, vec FLOAT[3])")
        con.execute(
            "INSERT INTO toy_vectors VALUES (1, [0.1, 0.2, 0.3]), (2, [0.9, 0.8, 0.7]), "
            "(3, [0.15, 0.18, 0.33])"
        )

        # HNSW indexes require experimental_persistent_index for on-disk databases
        con.execute("SET hnsw_enable_experimental_persistence = true")
        con.execute("CREATE INDEX toy_hnsw ON toy_vectors USING HNSW (vec)")

        rows = con.execute(
            "SELECT id, array_distance(vec, [0.1, 0.2, 0.3]::FLOAT[3]) AS d "
            "FROM toy_vectors ORDER BY d LIMIT 3"
        ).fetchall()
        print(f"Nearest-neighbor query result: {rows}")

        nearest_id = rows[0][0]
        if nearest_id != 1:
            print(
                f"[check_duckdb] FAIL: expected nearest id=1, got id={nearest_id}",
                file=sys.stderr,
            )
            return 1

        print("DuckDB + vss smoke test OK.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
