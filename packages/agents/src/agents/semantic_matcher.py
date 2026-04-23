"""Semantic Matcher — per-target-column retrieval + LLM rerank.

Flow per target column:
  1. Build canonical embedding text from the target ColumnProfile.
  2. Embed it.
  3. SourceVectorStore.top_k(k=10) -> top-K source candidates by vector distance.
  4. One LLM call that reranks the candidates and attaches per-candidate rationale.
  5. Emit CandidateSet (or mark no_match if the LLM sees nothing plausible).

The LLM only reranks within the retrieved K — it is NOT allowed to invent
source FQNs outside the retrieved list. We enforce this by post-filtering
the LLM output against the retrieved set.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from agents.embeddings import Embedder
from agents.llm import LLMClient, get_cached, prompt_cache_key
from agents.vector_store import Neighbor, SourceVectorStore, column_embed_text
from schemas import CandidateSet, ColumnProfile, MatchCandidate

log = logging.getLogger(__name__)


class RerankedCandidate(BaseModel):
    """LLM output — one reranked candidate."""

    source_fqn: str = Field(description="MUST be one of the retrieved candidate FQNs.")
    rationale: str = Field(description="One-sentence reason this source maps to the target.")
    similarity: float = Field(ge=0.0, le=1.0, description="LLM-judged 0..1 similarity.")


class MatcherOutput(BaseModel):
    """Structured output schema for one target column."""

    candidates: list[RerankedCandidate]
    no_match: bool = Field(
        default=False,
        description="True if none of the retrieved sources plausibly maps to this target.",
    )


_SYSTEM_PROMPT = """\
You are a DataOps expert matching a TARGET warehouse column to SOURCE OLTP columns.

You will be given:
  - A target column (name, type, description, semantic type)
  - A ranked list of source-column candidates retrieved by embedding similarity

Your job:
  - Rerank the candidates by how well each maps to the target
  - Keep AT MOST the candidates you'd actually consider using (prune obviously-wrong ones)
  - Set no_match=true if none of the candidates is a plausible source
  - For each kept candidate, write a single-sentence rationale and a calibrated
    similarity in [0,1] (1.0 = definitely the right source; 0.3 = plausible but uncertain)

Constraints:
  - `source_fqn` MUST match EXACTLY one of the retrieved candidate FQNs — no invention.
  - Order kept candidates best-first.

A target may legitimately match MULTIPLE sources (e.g. a FullName target composed of FirstName + MiddleName + LastName). In that case, return all the component sources, each with its own rationale."""


def _format_target(col: ColumnProfile) -> str:
    parts = [f"FQN: {col.fqn}", f"Type: {col.sql_type}"]
    if col.ms_description:
        parts.append(f"Description: {col.ms_description}")
    if col.inferred_semantic_type.value != "unknown":
        parts.append(f"Semantic type: {col.inferred_semantic_type.value}")
    return "\n".join(parts)


def _format_candidates(neighbors: list[Neighbor]) -> str:
    lines = ["Candidates (best-first by embedding distance):"]
    for i, nb in enumerate(neighbors, 1):
        bits = [f"{i}. {nb.fqn}", f"type={nb.sql_type}", f"d={nb.distance:.3f}"]
        if nb.ms_description:
            bits.append(f'desc="{nb.ms_description[:80]}"')
        if nb.top_values_text:
            bits.append(f"top_values={nb.top_values_text[:80]}")
        lines.append("  ".join(bits))
    return "\n".join(lines)


def match_target_columns(
    target_cols: list[ColumnProfile],
    store: SourceVectorStore,
    embedder: Embedder,
    llm: LLMClient,
    *,
    k: int = 10,
    rate_limit_delay_sec: float = 0.0,
) -> dict[str, CandidateSet]:
    """Return {target_fqn: CandidateSet} for every input target column."""
    if not target_cols:
        return {}

    # Batch-embed all target columns once (Voyage handles batching internally + cache)
    target_texts = [column_embed_text(c) for c in target_cols]
    target_embeddings = embedder.embed(target_texts)

    out: dict[str, CandidateSet] = {}
    total = len(target_cols)
    for idx, (col, emb) in enumerate(zip(target_cols, target_embeddings, strict=True), start=1):
        log.info("semantic_matcher %d/%d: %s", idx, total, col.fqn)
        neighbors = store.top_k(emb, k=k)
        made_call = _match_one(col, neighbors, llm, out)
        if made_call and rate_limit_delay_sec > 0 and idx < total:
            time.sleep(rate_limit_delay_sec)
    return out


def _match_one(
    target: ColumnProfile,
    neighbors: list[Neighbor],
    llm: LLMClient,
    out: dict[str, CandidateSet],
) -> bool:
    """Rerank `neighbors` for `target` via LLM; fill `out[target.fqn]`. Returns True on network call."""
    if not neighbors:
        out[target.fqn] = CandidateSet(target_fqn=target.fqn, candidates=[], no_match=True)
        return False

    user_prompt = (
        f"TARGET:\n{_format_target(target)}\n\n{_format_candidates(neighbors)}\n\n"
        "Return JSON matching the MatcherOutput schema."
    )

    # Cache peek for the sleep-skipping optimization
    key = prompt_cache_key(
        llm.provider, llm.model, _SYSTEM_PROMPT, user_prompt, MatcherOutput.__name__
    )
    cache_hit = get_cached(key) is not None

    try:
        result = llm.structured(_SYSTEM_PROMPT, user_prompt, MatcherOutput)
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic_matcher LLM call failed for %s: %s", target.fqn, exc)
        # Fall back to embedding-only ranking
        out[target.fqn] = _embedding_only_candidate_set(target.fqn, neighbors)
        return not cache_hit

    # Enforce: no hallucinated source FQNs
    valid_fqns = {nb.fqn for nb in neighbors}
    kept: list[MatchCandidate] = []
    for rc in result.candidates:
        if rc.source_fqn not in valid_fqns:
            log.warning(
                "semantic_matcher: LLM returned source_fqn %r not in retrieved set for %s; dropping.",
                rc.source_fqn,
                target.fqn,
            )
            continue
        # Store the LLM similarity (0..1) in embedding_similarity slot for M1;
        # M2 can split this into two fields. Negative distance isn't meaningful here.
        kept.append(
            MatchCandidate(
                source_fqn=rc.source_fqn,
                embedding_similarity=rc.similarity,
                rationale=rc.rationale,
            )
        )

    out[target.fqn] = CandidateSet(
        target_fqn=target.fqn,
        candidates=kept,
        no_match=result.no_match or len(kept) == 0,
    )
    return not cache_hit


def _embedding_only_candidate_set(target_fqn: str, neighbors: list[Neighbor]) -> CandidateSet:
    """Fallback when the LLM call fails — use raw embedding ranks with no rationale."""
    candidates = [
        MatchCandidate(
            source_fqn=nb.fqn,
            embedding_similarity=max(0.0, 1.0 - nb.distance),  # rough conversion
            rationale="(embedding-only fallback — LLM rerank failed)",
        )
        for nb in neighbors[:5]
    ]
    return CandidateSet(target_fqn=target_fqn, candidates=candidates, no_match=False)
