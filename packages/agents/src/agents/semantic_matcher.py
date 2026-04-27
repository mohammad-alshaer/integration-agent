"""Semantic Matcher — per-target-column retrieval + LLM rerank.

Flow per target column:
  1. Build canonical embedding text from the target ColumnProfile.
  2. Embed it.
  3. SourceVectorStore.top_k(k=15) -> top-K source candidates by vector distance.
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
from schemas import CandidateSet, ColumnProfile, MatchCandidate, SchemaProfile

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
  - A target column (name, type, description, semantic type, and target TABLE)
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

Domain alignment + specificity (read carefully — this is the most common failure mode):
  - WRONG-DOMAIN cases (drop entirely): candidates from a clearly different business domain are
    semantically WRONG even when they're structurally identical. Example: a target in
    `dbo.FactInternetSales` (about INTERNET SALES) MUST NOT pull from `Purchasing.*` (about VENDOR
    PURCHASES) — the columns happen to be named the same and have similar formulas, but they
    represent fundamentally different transactions. Drop wrong-domain candidates.
  - PARENT-vs-CHILD within the SAME domain (prefer the more specific): when two candidates from the
    SAME domain area both contain the target value (e.g. both `Sales.Customer.CustomerID` and its
    FK parent `Person.BusinessEntity.BusinessEntityID` carry the customer business key), PREFER THE
    MORE SPECIFIC source — the table closer to the target's semantic role wins. For a `DimCustomer`
    target, `Sales.Customer.CustomerID` beats `Person.BusinessEntity.BusinessEntityID`.

A target may legitimately match MULTIPLE sources (e.g. a FullName target composed of FirstName + MiddleName + LastName). In that case, return all the component sources, each with its own rationale.

A target may legitimately match sources spanning MULTIPLE TABLES (e.g. a fact-table allocation
column whose value comes from a header column allocated by a detail-line ratio). Return all
the contributing sources across both tables — don't stop at one table's columns.

About FK-EXTENDED candidates: candidates with `d=0.999` were added by an FK-aware second-pass
because their tables are FK-linked to one of the top-K's tables. Treat them as low-prior but
LOOK CLOSELY at them when the target appears to be a multi-table allocation (e.g. a fact-table
column at detail grain whose natural top-K is dominated by header-table columns). The FK-extended
candidate is often the missing detail-grain piece. Don't discard them just because their distance
is high — the distance is artificial."""


def _format_target(col: ColumnProfile) -> str:
    parts = [
        f"FQN: {col.fqn}",
        f"Target table: {col.table_schema}.{col.table_name}  (use this to filter domain-aligned sources)",
        f"Type: {col.sql_type}",
    ]
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
    k: int = 15,
    rate_limit_delay_sec: float = 0.0,
    source_profile: SchemaProfile | None = None,
    fk_extension_per_table: int = 3,
    max_fk_extension: int = 5,
) -> dict[str, CandidateSet]:
    """Return {target_fqn: CandidateSet} for every input target column.

    When source_profile is supplied, after the HNSW top-K retrieval we ALSO scan FK
    relationships of the top-K's source tables and append type-compatible columns from
    the FK-linked tables to the candidate set. This surfaces cross-table allocation
    candidates (e.g., Detail.LineTotal for a FactInternetSales.TaxAmt target whose
    natural top-K is dominated by Header.* columns).
    """
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
        if source_profile is not None:
            neighbors = _fk_extend_neighbors(
                col,
                neighbors,
                source_profile,
                max_per_fk_table=fk_extension_per_table,
                max_total_extension=max_fk_extension,
            )
        made_call = _match_one(col, neighbors, llm, out)
        if made_call and rate_limit_delay_sec > 0 and idx < total:
            time.sleep(rate_limit_delay_sec)
    return out


def _type_category(sql_type: str) -> str:
    """Coarse type bucket for FK-extension type compatibility."""
    s = sql_type.lower()
    if any(t in s for t in ("decimal", "numeric", "money", "int", "bigint", "smallint", "tinyint", "float", "real", "double")):
        return "numeric"
    if any(t in s for t in ("varchar", "nvarchar", "char", "nchar", "text", "ntext")):
        return "string"
    if any(t in s for t in ("date", "time", "timestamp")):
        return "temporal"
    if "bit" in s or "bool" in s:
        return "boolean"
    return "other"


def _fk_extend_neighbors(
    target: ColumnProfile,
    neighbors: list[Neighbor],
    source_profile: SchemaProfile,
    *,
    max_per_fk_table: int = 3,
    max_total_extension: int = 5,
) -> list[Neighbor]:
    """Append candidates from FK-linked tables of the top-K's source tables.

    For each unique source table in the top-K, find tables linked via ColumnProfile.fk_ref
    in either direction (this table's FK -> other table; other table's FK -> this table).
    From each FK-linked table, take up to max_per_fk_table type-compatible columns whose
    FQN isn't already in neighbors. Cap total additions at max_total_extension.
    """
    target_type_cat = _type_category(target.sql_type)
    seen_fqns = {nb.fqn for nb in neighbors}
    seen_tables: set[tuple[str, str]] = set()
    for nb in neighbors:
        parts = nb.fqn.split(".")
        if len(parts) >= 2:
            seen_tables.add((parts[0], parts[1]))

    cols_by_table: dict[tuple[str, str], list[ColumnProfile]] = {}
    for tbl in source_profile.tables:
        cols_by_table[(tbl.table_schema, tbl.table_name)] = list(tbl.columns)

    fk_targets: set[tuple[str, str]] = set()
    for (schema, table) in seen_tables:
        cols = cols_by_table.get((schema, table), [])
        # Direction 1: this table has FK pointing OUT to another
        for col in cols:
            if not col.fk_ref:
                continue
            ref_parts = col.fk_ref.split(".")
            if len(ref_parts) >= 2:
                ref_pair = (ref_parts[0], ref_parts[1])
                if ref_pair not in seen_tables:
                    fk_targets.add(ref_pair)
        # Direction 2: another table has FK pointing IN to this one
        prefix = f"{schema}.{table}."
        for other_pair, other_cols in cols_by_table.items():
            if other_pair in seen_tables or other_pair in fk_targets:
                continue
            for ocol in other_cols:
                if ocol.fk_ref and ocol.fk_ref.startswith(prefix):
                    fk_targets.add(other_pair)
                    break

    extensions: list[Neighbor] = []
    for fk_pair in sorted(fk_targets):
        if len(extensions) >= max_total_extension:
            break
        added_for_table = 0
        for col in cols_by_table.get(fk_pair, []):
            if added_for_table >= max_per_fk_table:
                break
            if len(extensions) >= max_total_extension:
                break
            if col.fqn in seen_fqns:
                continue
            if _type_category(col.sql_type) != target_type_cat and target_type_cat != "other":
                continue
            extensions.append(
                Neighbor(
                    fqn=col.fqn,
                    sql_type=col.sql_type,
                    ms_description=col.ms_description,
                    top_values_text=None,
                    distance=0.999,  # Larger than any real HNSW distance — sorted last
                )
            )
            seen_fqns.add(col.fqn)
            added_for_table += 1

    if extensions:
        log.info(
            "semantic_matcher: FK-extended %s with %d candidates from %d FK-linked tables",
            target.fqn,
            len(extensions),
            len({(e.fqn.split('.')[0], e.fqn.split('.')[1]) for e in extensions}),
        )
    return neighbors + extensions


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
