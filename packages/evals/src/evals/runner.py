"""End-to-end runner: load profiles + golden -> invoke graph -> score -> JSON report."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agents.embeddings import Embedder
from agents.graph import build_graph
from agents.llm import LLMClient
from agents.vector_store import SourceVectorStore
from evals.golden import load_expected
from evals.models import EvalReport
from evals.scorer import score
from schemas import MappingSpec, SchemaProfile
from validator import Sandbox

log = logging.getLogger(__name__)


@dataclass
class RunnerConfig:
    pair: str
    provider: str
    model: str
    source_profile: Path
    target_profile: Path
    golden: Path
    out: Path
    vector_db: Path = Path(".duckdb/integration_agent.duckdb")
    sample_dir: Path | None = None
    rebuild_index: bool = False
    k: int = 10
    rate_limit_delay: float = 6.5
    max_retries: int = 1


def _build_llm(provider: str) -> LLMClient:
    if provider == "gemini":
        from agents.llm import GeminiProvider

        return GeminiProvider()
    if provider == "fake":
        from evals._fakes import build_smoke_fake_llm

        return build_smoke_fake_llm()
    raise ValueError(f"unknown provider {provider!r}; expected 'gemini' or 'fake'")


def _build_embedder(provider: str) -> Embedder:
    if provider == "fake":
        from evals._fakes import ConstantEmbedder

        return ConstantEmbedder()
    from agents.embeddings import default_embedder

    return default_embedder()


def run_eval(cfg: RunnerConfig) -> EvalReport:
    log.info("evals.run_eval pair=%s provider=%s model=%s", cfg.pair, cfg.provider, cfg.model)
    source = SchemaProfile.model_validate_json(cfg.source_profile.read_text(encoding="utf-8"))
    target = SchemaProfile.model_validate_json(cfg.target_profile.read_text(encoding="utf-8"))
    expected_file = load_expected(cfg.golden)
    target_fqns = [m.target_fqn for m in expected_file.mappings]
    log.info(
        "loaded source=%s (%d tables) target=%s (%d tables) golden=%d mappings",
        source.database_name,
        len(source.tables),
        target.database_name,
        len(target.tables),
        len(expected_file.mappings),
    )

    llm = _build_llm(cfg.provider)
    embedder = _build_embedder(cfg.provider)
    store = SourceVectorStore(cfg.vector_db, embedder)
    if cfg.rebuild_index:
        store.reset()
    store.add_columns(source)

    sandbox = Sandbox(cfg.sample_dir) if cfg.sample_dir is not None else None
    graph = build_graph(
        embedder,
        llm,
        store,
        k_candidates=cfg.k,
        rate_limit_delay_sec=cfg.rate_limit_delay,
        sandbox=sandbox,
        max_retries=cfg.max_retries,
    )

    initial: dict = {
        "source_profile": source,
        "target_profile": target,
        "target_fqns": target_fqns,
    }
    try:
        final_state = graph.invoke(initial)
        specs: list[MappingSpec] = final_state.get("specs", [])
    finally:
        store.close()
        if sandbox is not None:
            sandbox.close()

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = score(expected_file, specs, provider=cfg.provider, model=cfg.model, run_id=run_id)

    cfg.out.parent.mkdir(parents=True, exist_ok=True)
    cfg.out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    log.info("wrote EvalReport to %s", cfg.out)
    return report


__all__ = ["RunnerConfig", "run_eval"]
