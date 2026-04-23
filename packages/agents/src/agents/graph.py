"""LangGraph assembly — the Week 3 M1 pipeline wired as a StateGraph.

Flow (no retry loop in W3; Validator retries land in W4):
    START -> semantic_matcher -> pattern_classifier -> transformation_generator -> END

State carries the Pydantic artifacts between steps. Dependencies (embedder,
LLM client, vector store) are closed over by the node functions at build time
— this keeps the state serializable and the nodes cheap.
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
    PatternClassification,
    SchemaProfile,
)

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
):
    """Compile a LangGraph StateGraph bound to these deps."""

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
        log.info(
            "graph/transformation_generator: %d classifications -> specs",
            len(state.get("classifications", {})),
        )
        specs = generate_mappings(
            state.get("classifications", {}),
            target_map,
            source_map,
            llm,
        )
        return {"specs": specs}

    g: StateGraph = StateGraph(GraphState)
    g.add_node("semantic_matcher", semantic_matcher_node)
    g.add_node("pattern_classifier", pattern_classifier_node)
    g.add_node("transformation_generator", transformation_generator_node)
    g.add_edge(START, "semantic_matcher")
    g.add_edge("semantic_matcher", "pattern_classifier")
    g.add_edge("pattern_classifier", "transformation_generator")
    g.add_edge("transformation_generator", END)
    return g.compile()
