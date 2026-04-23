"""Typer-based CLI for Integration-Agent.

Subcommands:
  profile   introspect a SQL Server database, compute profile stats, sample to
            Parquet, enrich with the LLM Schema Explorer, write SchemaProfile JSON.
"""

# Corporate TLS proxy: route Python TLS through Windows cert store.
# Must happen before any HTTPS client is constructed (LLMClient, Langfuse, etc.).
import truststore

truststore.inject_into_ssl()

import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agents.embeddings import default_embedder  # noqa: E402
from agents.graph import build_graph  # noqa: E402
from agents.llm import GeminiProvider  # noqa: E402
from agents.schema_explorer import enrich_schema  # noqa: E402
from agents.vector_store import SourceVectorStore  # noqa: E402
from schemas import SchemaProfile  # noqa: E402
from sqlserver import connect, introspect_schema, profile_tables, sample_to_parquet  # noqa: E402

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = typer.Typer(help="Integration-Agent CLI.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the worker package version."""
    from importlib.metadata import version as _v

    typer.echo(_v("integration-agent-worker"))


@app.command()
def profile(
    db: str = typer.Option(..., help="Database name on SQLDEV2025 (e.g. AdventureWorks2022)."),
    role: str = typer.Option(..., help="source | target"),
    out: Path = typer.Option(..., help="Output path for the SchemaProfile JSON."),
    sample_dir: Path = typer.Option(
        Path("benchmarks/adventureworks/samples"),
        help="Directory for Parquet samples (gitignored).",
    ),
    n_sample: int = typer.Option(1000, help="Rows per seed table to sample."),
    include_samples: bool = typer.Option(True, help="Write Parquet samples."),
    enrich: bool = typer.Option(True, help="Run LLM semantic-type enrichment (Schema Explorer)."),
    tables: list[str] | None = typer.Option(
        None,
        "--table",
        help="Restrict sampling (and enrichment) to specific schema.table names. "
        "Profile still covers all tables so mapping can find them later.",
    ),
    rate_limit_delay: float = typer.Option(
        0.0,
        help="Seconds to sleep between LLM calls on cache-miss (Gemini Flash free tier = 10 RPM, so ~6.5s).",
    ),
) -> None:
    """Profile a database end to end: introspect -> profile_stats -> sample -> enrich -> JSON."""
    if role not in ("source", "target"):
        raise typer.BadParameter("role must be 'source' or 'target'")

    out.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"[1/4] Connecting to {db} ...")
    conn = connect(db)

    typer.echo(f"[2/4] Introspecting {db} ...")
    profile = introspect_schema(conn, db, role=role)
    typer.echo(
        f"      {len(profile.tables)} tables, {sum(len(t.columns) for t in profile.tables)} columns."
    )

    typer.echo("[3/4] Profiling stats (null_rate, distinct, top_values, min/max) ...")
    profile_tables(conn, profile)

    if include_samples:
        typer.echo(
            f"[3.5/4] Sampling {n_sample} rows per table (FK-closure one hop) to {sample_dir} ..."
        )
        seed_tables: list[tuple[str, str]] | None = None
        if tables:
            seed_tables = [tuple(t.split(".", 1)) for t in tables]  # type: ignore[misc]
        sample_to_parquet(
            conn,
            profile,
            sample_dir,
            seed_tables=seed_tables,
            n_per_table=n_sample,
        )

    if enrich:
        typer.echo("[4/4] Enriching schema via LLM (Schema Explorer) ...")
        llm = GeminiProvider()
        only: list[tuple[str, str]] | None = None
        if tables:
            only = [tuple(t.split(".", 1)) for t in tables]  # type: ignore[misc]
        enrich_schema(profile, llm, only_tables=only, rate_limit_delay_sec=rate_limit_delay)
    else:
        typer.echo("[4/4] Skipping LLM enrichment (--no-enrich).")

    typer.echo(f"Writing SchemaProfile JSON -> {out}")
    out.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    typer.echo("Done.")


@app.command()
def run(
    source_profile: Path = typer.Option(
        ..., help="Path to source SchemaProfile JSON (from `profile`)."
    ),
    target_profile: Path = typer.Option(
        ..., help="Path to target SchemaProfile JSON (from `profile`)."
    ),
    targets: list[str] | None = typer.Option(
        None,
        "--target-table",
        help="Restrict mapping to the given target table (e.g. dbo.DimCustomer). Repeat to add more.",
    ),
    vector_db: Path = typer.Option(
        Path(".duckdb/integration_agent.duckdb"),
        help="DuckDB file for the source embedding index.",
    ),
    rebuild_index: bool = typer.Option(
        False, help="Drop + rebuild the source embedding index before running."
    ),
    k: int = typer.Option(10, help="Top-K source candidates per target column."),
    rate_limit_delay: float = typer.Option(
        0.0,
        help="Seconds to sleep between cache-miss LLM calls (Gemini Flash free tier: use ~6.5).",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="If true, print MappingSpec JSON to stdout and skip any persistence. (W4 adds dbt emit + validator.)",
    ),
    out: Path | None = typer.Option(
        None, help="Optional: write the MappingSpec list to this JSON file."
    ),
) -> None:
    """Run the W3 mapping graph: semantic_matcher -> pattern_classifier -> transformation_generator."""
    source = SchemaProfile.model_validate_json(source_profile.read_text(encoding="utf-8"))
    target = SchemaProfile.model_validate_json(target_profile.read_text(encoding="utf-8"))
    typer.echo(f"Loaded source: {source.database_name} ({len(source.tables)} tables)")
    typer.echo(f"Loaded target: {target.database_name} ({len(target.tables)} tables)")

    # Filter target columns by table
    target_fqns: list[str] = []
    if targets:
        wanted_tables: set[tuple[str, str]] = set()
        for t in targets:
            parts = t.split(".", 1)
            if len(parts) != 2:
                raise typer.BadParameter(f"--target-table must be schema.table, got {t!r}")
            wanted_tables.add((parts[0], parts[1]))
        for t in target.tables:
            if (t.table_schema, t.table_name) in wanted_tables:
                target_fqns.extend(c.fqn for c in t.columns)
        typer.echo(
            f"Restricting to {len(target_fqns)} target columns across {len(wanted_tables)} table(s)"
        )
    else:
        for t in target.tables:
            target_fqns.extend(c.fqn for c in t.columns)
        typer.echo(f"Mapping ALL {len(target_fqns)} target columns")

    embedder = default_embedder()
    typer.echo(
        f"Embedder: provider={embedder.provider} model={embedder.model} dims={embedder.dims}"
    )
    store = SourceVectorStore(vector_db, embedder)
    if rebuild_index:
        store.reset()
    typer.echo(
        f"Indexing {sum(len(t.columns) for t in source.tables)} source columns into {vector_db} ..."
    )
    store.add_columns(source)

    llm = GeminiProvider()
    graph = build_graph(embedder, llm, store, k_candidates=k, rate_limit_delay_sec=rate_limit_delay)

    initial: dict = {
        "source_profile": source,
        "target_profile": target,
        "target_fqns": target_fqns,
    }
    final_state = graph.invoke(initial)
    specs = final_state.get("specs", [])

    typer.echo(f"\n=== {len(specs)} MappingSpec(s) emitted ===\n")
    if dry_run:
        for s in specs:
            typer.echo(s.model_dump_json(indent=2))
            typer.echo("")

    # Report unsupported / skipped
    classifications = final_state.get("classifications", {})
    unsupported = sum(
        1 for pc in classifications.values() if pc.pattern.value == "unsupported_in_m1"
    )
    typer.echo(
        f"Classifications: {len(classifications)} total, {unsupported} unsupported_in_m1 (skipped)"
    )

    if out is not None:
        payload = [s.model_dump() for s in specs]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        typer.echo(f"Wrote {len(specs)} specs to {out}")

    store.close()
    typer.echo("Done.")
