"""Typer CLI for the evals package. `python -m evals run ...`"""

import truststore

truststore.inject_into_ssl()

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from evals.runner import RunnerConfig, run_eval  # noqa: E402

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = typer.Typer(help="Integration-Agent evals CLI.", no_args_is_help=True)

_PAIR_DEFAULTS: dict[str, dict[str, Path]] = {
    "adventureworks": {
        "source_profile": Path("tmp/profiles/aw2022.json"),
        "target_profile": Path("tmp/profiles/awdw2022.json"),
        "golden": Path("benchmarks/adventureworks/expected_mappings.yaml"),
        "out": Path("benchmarks/adventureworks/out/eval_report.json"),
        "sample_dir": Path("benchmarks/adventureworks/samples"),
    },
}


@app.command()
def run(
    pair: str = typer.Option("adventureworks", help="Benchmark pair (resolves default paths)."),
    provider: str = typer.Option("gemini", help="LLM provider: gemini | fake"),
    model: str = typer.Option("gemini-2.5-flash", help="Model id"),
    source_profile: Path | None = typer.Option(
        None, help="Override source SchemaProfile JSON path."
    ),
    target_profile: Path | None = typer.Option(
        None, help="Override target SchemaProfile JSON path."
    ),
    golden: Path | None = typer.Option(None, help="Override expected_mappings.yaml path."),
    out: Path | None = typer.Option(None, help="Override eval_report.json output path."),
    vector_db: Path = typer.Option(
        Path(".duckdb/integration_agent.duckdb"),
        help="DuckDB file for the source embedding index.",
    ),
    sample_dir: Path | None = typer.Option(
        None, help="Parquet sample directory for the validator sandbox."
    ),
    rebuild_index: bool = typer.Option(
        False, help="Drop + rebuild the source embedding index before running."
    ),
    k: int = typer.Option(15, help="Top-K source candidates per target column."),
    rate_limit_delay: float = typer.Option(
        6.5, help="Seconds to sleep between cache-miss LLM calls (Flash free tier: 6.5)."
    ),
    max_retries: int = typer.Option(1, help="Max validator-triggered retries on DERIVED failures."),
) -> None:
    """Run the mapping graph against the golden set and write an EvalReport JSON."""
    if pair not in _PAIR_DEFAULTS:
        raise typer.BadParameter(f"unknown pair {pair!r}; known: {sorted(_PAIR_DEFAULTS)}")
    d = _PAIR_DEFAULTS[pair]
    cfg = RunnerConfig(
        pair=pair,
        provider=provider,
        model=model,
        source_profile=source_profile or d["source_profile"],
        target_profile=target_profile or d["target_profile"],
        golden=golden or d["golden"],
        out=out or d["out"],
        sample_dir=sample_dir if sample_dir is not None else d.get("sample_dir"),
        vector_db=vector_db,
        rebuild_index=rebuild_index,
        k=k,
        rate_limit_delay=rate_limit_delay,
        max_retries=max_retries,
    )
    typer.echo(f"pair={cfg.pair} provider={cfg.provider} model={cfg.model}")
    typer.echo(f"source={cfg.source_profile} target={cfg.target_profile}")
    typer.echo(f"golden={cfg.golden} out={cfg.out}")
    typer.echo(f"sample_dir={cfg.sample_dir} vector_db={cfg.vector_db}")

    report = run_eval(cfg)
    incl = report.rates.get("inclusive", {})
    excl = report.rates.get("exclusive", {})
    typer.echo(f"\nEvalReport written -> {cfg.out}")
    typer.echo(f"  expected={report.expected_count} actual={report.actual_count}")
    typer.echo(
        f"  exact:        inclusive={incl.get('exact', 0):.1%}  exclusive={excl.get('exact', 0):.1%}"
    )
    typer.echo(
        f"  pattern:      inclusive={incl.get('pattern', 0):.1%}  exclusive={excl.get('pattern', 0):.1%}"
    )
    typer.echo(
        f"  sql_semantic: inclusive={incl.get('sql_semantic', 0):.1%}  exclusive={excl.get('sql_semantic', 0):.1%}"
    )
    typer.echo(
        f"  missing={report.missing_count} extra={report.extra_count} mismatch={report.mismatch_count}"
    )
