"""LangGraph assembly — M1 pipeline wired as a StateGraph.

Flow:
    START -> semantic_matcher -> pattern_classifier -> transformation_generator -> validator
               -> (conditional) retry back into transformation_generator, or END

State carries the Pydantic artifacts between steps. Dependencies (embedder,
LLM client, vector store, validator sandbox) are closed over by the node
functions at build time — keeps the state serializable and the nodes cheap.

Retry contract:
  - The validator node fills `validation_reports` on every pass.
  - `should_retry` routes back to `transformation_generator` when any DERIVED
    spec failed AND `retry_count < max_retries`. Rename / concat generators
    are deterministic; their failures aren't retry-fixable at this layer.
  - On the retry pass, `transformation_generator` reads the reports, builds
    `error_hints_by_target`, and passes them through to the generators.
    DerivedGenerator's prompt appends a "previous attempt failed" section so
    the LLM gets targeted feedback, not just a blind regenerate signal.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents.embeddings import Embedder
from agents.llm import LLMClient
from agents.pattern_classifier import classify_target_columns
from agents.semantic_matcher import match_target_columns
from agents.transformation_generator import generate_mappings
from agents.vector_store import SourceVectorStore
from schemas import (
    CandidateSet,
    ColumnProfile,
    MappingSpec,
    Pattern,
    PatternClassification,
    SchemaProfile,
    ValidationReport,
)
from validator import Sandbox, validate_specs

log = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    """Serializable state passed between graph nodes.

    Only `source_profile` / `target_profile` / `target_fqns` are required as
    entry-point inputs; the rest are populated by the nodes as they run.
    """

    source_profile: SchemaProfile
    target_profile: SchemaProfile
    target_fqns: list[str]  # restrict which target columns to map; empty => all

    # Populated during the run
    candidate_sets: dict[str, CandidateSet]
    classifications: dict[str, PatternClassification]
    specs: list[MappingSpec]
    validation_reports: dict[str, ValidationReport]
    retry_count: int


def _select_targets(state: GraphState) -> list[ColumnProfile]:
    wanted = set(state.get("target_fqns") or [])
    cols: list[ColumnProfile] = []
    for t in state["target_profile"].tables:
        for c in t.columns:
            if not wanted or c.fqn in wanted:
                cols.append(c)
    return cols


def _source_columns_by_fqn(profile: SchemaProfile) -> dict[str, ColumnProfile]:
    return {c.fqn: c for t in profile.tables for c in t.columns}


def build_graph(
    embedder: Embedder,
    llm: LLMClient,
    store: SourceVectorStore,
    *,
    k_candidates: int = 10,
    rate_limit_delay_sec: float = 0.0,
    sandbox: Sandbox | None = None,
    max_retries: int = 1,
):
    """Compile a LangGraph StateGraph bound to these deps.

    sandbox: if None, the validator node short-circuits (no reports) and the
      conditional retry edge always routes to END. Useful for CLI dry-runs
      before W4's dbt_emit + evals land.
    max_retries: number of retry passes. 1 means (initial + 1 retry = 2 total
      transformation_generator invocations); 0 disables retries entirely.
    """

    def semantic_matcher_node(state: GraphState) -> dict:
        targets = _select_targets(state)
        log.info("graph/semantic_matcher: %d target columns", len(targets))
        cs = match_target_columns(
            targets,
            store,
            embedder,
            llm,
            k=k_candidates,
            rate_limit_delay_sec=rate_limit_delay_sec,
        )
        return {"candidate_sets": cs}

    def pattern_classifier_node(state: GraphState) -> dict:
        targets = _select_targets(state)
        log.info("graph/pattern_classifier: %d target columns", len(targets))
        pc = classify_target_columns(
            targets,
            state.get("candidate_sets", {}),
            llm,
            rate_limit_delay_sec=rate_limit_delay_sec,
        )
        return {"classifications": pc}

    def transformation_generator_node(state: GraphState) -> dict:
        targets = _select_targets(state)
        target_map = {c.fqn: c for c in targets}
        source_map = _source_columns_by_fqn(state["source_profile"])

        reports = state.get("validation_reports", {}) or {}
        error_hints_by_target = {
            fqn: rep.errors for fqn, rep in reports.items() if not rep.passed and rep.errors
        }
        is_retry = bool(error_hints_by_target)

        log.info(
            "graph/transformation_generator: %d classifications -> specs%s",
            len(state.get("classifications", {})),
            f" (retry pass — {len(error_hints_by_target)} targets with hints)" if is_retry else "",
        )

        specs = generate_mappings(
            state.get("classifications", {}),
            target_map,
            source_map,
            llm,
            error_hints_by_target=error_hints_by_target if is_retry else None,
        )
        new_retry = state.get("retry_count", 0) + (1 if is_retry else 0)
        return {"specs": specs, "retry_count": new_retry}

    def validator_node(state: GraphState) -> dict:
        specs = state.get("specs", [])
        if sandbox is None or not specs:
            log.info(
                "graph/validator: skipped (%s)", "no sandbox" if sandbox is None else "no specs"
            )
            return {"validation_reports": {}}
        reports = validate_specs(specs, sandbox, source_profile=state["source_profile"])
        n_passed = sum(1 for r in reports.values() if r.passed)
        log.info("graph/validator: %d/%d specs passed", n_passed, len(reports))
        return {"validation_reports": reports}

    def should_retry(state: GraphState) -> str:
        reports = state.get("validation_reports", {}) or {}
        if not reports:
            return "done"
        retries = state.get("retry_count", 0)
        if retries >= max_retries:
            return "done"

        specs_by_fqn = {s.target_fqn: s for s in state.get("specs", [])}
        failing_derived = [
            fqn
            for fqn, rep in reports.items()
            if not rep.passed
            and specs_by_fqn.get(fqn) is not None
            and specs_by_fqn[fqn].pattern == Pattern.DERIVED
        ]
        if failing_derived:
            log.info(
                "graph/validator: %d failing DERIVED specs, scheduling retry (%d/%d used)",
                len(failing_derived),
                retries,
                max_retries,
            )
            return "retry"
        return "done"

    g: StateGraph = StateGraph(GraphState)
    g.add_node("semantic_matcher", semantic_matcher_node)
    g.add_node("pattern_classifier", pattern_classifier_node)
    g.add_node("transformation_generator", transformation_generator_node)
    g.add_node("validator", validator_node)

    g.add_edge(START, "semantic_matcher")
    g.add_edge("semantic_matcher", "pattern_classifier")
    g.add_edge("pattern_classifier", "transformation_generator")
    g.add_edge("transformation_generator", "validator")
    g.add_conditional_edges(
        "validator",
        should_retry,
        {"retry": "transformation_generator", "done": END},
    )
    return g.compile()
