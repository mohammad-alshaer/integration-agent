"""Smoke test: embed a handful of AdventureWorks columns + nearest-neighbor lookup.

Verifies:
  - truststore + VOYAGE_API_KEY -> voyageai client can reach the Voyage API
  - DuckDB + vss HNSW index builds on persistent file
  - array_distance returns sensible nearest-neighbor order

Run: ./.venv/Scripts/python.exe scripts/smoke_embeddings.py
"""

from __future__ import annotations

# Corporate TLS proxy
import truststore

truststore.inject_into_ssl()

from pathlib import Path  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

from agents.embeddings import VoyageEmbedder  # noqa: E402
from agents.vector_store import SourceVectorStore, column_embed_text  # noqa: E402
from schemas import ColumnProfile, SchemaProfile, TableProfile  # noqa: E402

load_dotenv()


def _col(schema: str, table: str, name: str, pos: int, sql_type: str, desc: str | None = None) -> ColumnProfile:
    return ColumnProfile(
        table_schema=schema,
        table_name=table,
        column_name=name,
        ordinal_position=pos,
        sql_type=sql_type,
        is_nullable=False,
        is_primary_key=False,
        is_foreign_key=False,
        ms_description=desc,
        null_rate=0.0,
        distinct_count=100,
        total_count=100,
    )


def main() -> int:
    profile = SchemaProfile(
        database_name="toy",
        role="source",
        tables=[
            TableProfile(
                table_schema="Person",
                table_name="Person",
                row_count_estimate=19972,
                columns=[
                    _col("Person", "Person", "FirstName", 5, "nvarchar(50)", "First name of the person."),
                    _col("Person", "Person", "LastName", 7, "nvarchar(50)", "Last name of the person."),
                    _col("Person", "Person", "MiddleName", 6, "nvarchar(50)", "Middle name or initial."),
                    _col("Person", "Person", "BusinessEntityID", 1, "int", "Primary key for the person."),
                ],
            ),
            TableProfile(
                table_schema="Sales",
                table_name="SalesOrderHeader",
                row_count_estimate=31465,
                columns=[
                    _col("Sales", "SalesOrderHeader", "OrderDate", 6, "datetime", "Dates the sales order was created."),
                    _col("Sales", "SalesOrderHeader", "TotalDue", 25, "money", "Total due including tax and freight."),
                    _col("Sales", "SalesOrderHeader", "SubTotal", 23, "money", "Sales subtotal before tax."),
                ],
            ),
        ],
        profiled_at="2026-04-23T00:00:00+00:00",
    )

    embedder = VoyageEmbedder()
    print(f"Embedder: model={embedder.model} dims={embedder.dims}")

    store_path = Path(".duckdb/smoke_source_embeddings.duckdb")
    if store_path.exists():
        store_path.unlink()

    store = SourceVectorStore(store_path, embedder)
    n = store.add_columns(profile)
    print(f"Indexed {n} source columns.")

    # Query 1: target column very similar to Person.Person.FirstName
    target_text = "DimCustomer.FirstName | type: nvarchar(50) | description: First name of the customer."
    q_emb = embedder.embed([target_text])[0]
    neighbors = store.top_k(q_emb, k=5)
    print(f"\nTarget: {target_text}")
    for nb in neighbors:
        print(f"  d={nb.distance:.4f}  {nb.fqn}  ({nb.sql_type})")

    # Query 2: target column very similar to Sales.SalesOrderHeader.TotalDue
    target_text = "FactInternetSales.SalesAmount | type: money | description: Total sales amount for the order."
    q_emb = embedder.embed([target_text])[0]
    neighbors = store.top_k(q_emb, k=5)
    print(f"\nTarget: {target_text}")
    for nb in neighbors:
        print(f"  d={nb.distance:.4f}  {nb.fqn}  ({nb.sql_type})")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
