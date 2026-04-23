"""Typer-based CLI for Integration-Agent.

Subcommands:
  profile   introspect a SQL Server database, compute profile stats, sample to
            Parquet, enrich with the LLM Schema Explorer, write SchemaProfile JSON.
"""

# Corporate TLS proxy: route Python TLS through Windows cert store.
# Must happen before any HTTPS client is constructed (LLMClient, Langfuse, etc.).
import truststore

truststore.inject_into_ssl()

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agents.llm import GeminiProvider  # noqa: E402
from agents.schema_explorer import enrich_schema  # noqa: E402
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
