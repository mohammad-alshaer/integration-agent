"""DuckDB + `vss` backed source-column embedding store.

The Semantic Matcher queries source columns keyed by target-column embedding,
so the store holds SOURCE embeddings and we query with TARGET text.

Schema:
    CREATE TABLE source_embeddings (
        fqn              VARCHAR PRIMARY KEY,    -- schema.table.column
        sql_type         VARCHAR,
        ms_description   VARCHAR,
        top_values_text  VARCHAR,
        embedding        FLOAT[dims]
    );
    CREATE INDEX ... USING HNSW (embedding);

DuckDB requires `SET hnsw_enable_experimental_persistence = true` for HNSW on
persistent files (as of DuckDB 1.5). This is acceptable for M1 but we should
revisit when DuckDB declares the feature stable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb

from agents.embeddings import Embedder
from schemas import ColumnProfile, SchemaProfile

log = logging.getLogger(__name__)


@dataclass
class Neighbor:
    """One nearest-neighbor search result."""

    fqn: str
    sql_type: str
    ms_description: str | None
    top_values_text: str | None
    distance: float


def column_embed_text(col: ColumnProfile) -> str:
    """Canonical embedding input for a column. Stable across source / target."""
    parts = [
        f"{col.table_schema}.{col.table_name}.{col.column_name}",
        f"type: {col.sql_type}",
    ]
    if col.ms_description:
        parts.append(f"description: {col.ms_description}")
    if col.top_values:
        tv = ", ".join(repr(v) for v, _ in col.top_values[:5])
        parts.append(f"top values: {tv}")
    if col.inferred_semantic_type.value != "unknown":
        parts.append(f"semantic type: {col.inferred_semantic_type.value}")
    return " | ".join(parts)


class SourceVectorStore:
    """Single-table DuckDB+vss index over the source-schema columns."""

    def __init__(
        self,
        db_path: Path,
        embedder: Embedder,
        *,
        table_name: str = "source_embeddings",
    ) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(db_path))
        self._con.execute("INSTALL vss")
        self._con.execute("LOAD vss")
        self._con.execute("SET hnsw_enable_experimental_persistence = true")
        self._embedder = embedder
        self._table = table_name
        self._dims = embedder.dims
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table} (
                fqn              VARCHAR PRIMARY KEY,
                sql_type         VARCHAR,
                ms_description   VARCHAR,
                top_values_text  VARCHAR,
                embedding        FLOAT[{self._dims}]
            )
            """
        )

    def reset(self) -> None:
        """Drop + recreate the table (useful between runs on different source schemas)."""
        self._con.execute(f"DROP INDEX IF EXISTS {self._table}_hnsw")
        self._con.execute(f"DROP TABLE IF EXISTS {self._table}")
        self._ensure_schema()

    def add_columns(self, profile: SchemaProfile) -> int:
        """Embed every column in `profile` and upsert into the store. Returns rows written."""
        columns = [c for t in profile.tables for c in t.columns]
        if not columns:
            return 0

        texts = [column_embed_text(c) for c in columns]
        log.info("vector_store: embedding %d source columns ...", len(texts))
        vectors = self._embedder.embed(texts)

        # INSERT OR REPLACE by PK
        for col, emb in zip(columns, vectors, strict=True):
            top_text = (
                ", ".join(f"{v!r}:{n}" for v, n in col.top_values[:5]) if col.top_values else None
            )
            self._con.execute(
                f"INSERT OR REPLACE INTO {self._table} VALUES (?, ?, ?, ?, ?::FLOAT[{self._dims}])",
                [col.fqn, col.sql_type, col.ms_description, top_text, emb],
            )

        # Build or rebuild the HNSW index after bulk load
        self._con.execute(f"DROP INDEX IF EXISTS {self._table}_hnsw")
        self._con.execute(
            f"CREATE INDEX {self._table}_hnsw ON {self._table} USING HNSW (embedding)"
        )
        return len(columns)

    def top_k(self, query_embedding: list[float], k: int = 10) -> list[Neighbor]:
        """Return the k nearest-neighbor rows by cosine-via-L2 on unit vectors.

        Voyage embeddings are L2-normalized by default, so array_distance (L2)
        ordering equals (1 - cosine) ordering. We expose `distance` as-is.
        """
        rows = self._con.execute(
            f"""
            SELECT fqn, sql_type, ms_description, top_values_text,
                   array_distance(embedding, ?::FLOAT[{self._dims}]) AS d
            FROM {self._table}
            ORDER BY d
            LIMIT ?
            """,
            [query_embedding, k],
        ).fetchall()
        return [
            Neighbor(
                fqn=r[0],
                sql_type=r[1],
                ms_description=r[2],
                top_values_text=r[3],
                distance=float(r[4]),
            )
            for r in rows
        ]

    def close(self) -> None:
        self._con.close()
