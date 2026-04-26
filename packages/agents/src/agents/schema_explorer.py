"""Schema Explorer — LLM enrichment of a SchemaProfile.

For each table, one structured-output call classifies every column's
`inferred_semantic_type` and `quality_flags`. Batching per-table keeps the call
count low (71 tables for AdventureWorks2022 = ~71 calls, well within Gemini
free tier once the prompt-hash cache is warm).

Output is folded back into the input `SchemaProfile` in place. Mutation style
is chosen to keep call sites simple; callers can persist by serializing the
returned profile to JSON.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from agents.llm import LLMClient
from schemas import QualityFlag, SchemaProfile, SemanticType, TableProfile

log = logging.getLogger(__name__)


class ColumnEnrichment(BaseModel):
    """LLM-emitted enrichment for one column."""

    column_name: str
    inferred_semantic_type: SemanticType
    semantic_type_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    quality_flags: list[QualityFlag] = []
    generated_description: str | None = Field(
        default=None,
        description=(
            "1-2 sentence description generated when ms_description is null/empty. "
            "Folded into ColumnProfile.ms_description so downstream embedders see it. "
            "Return null if ms_description is already populated."
        ),
    )


class TableEnrichment(BaseModel):
    """Structured output: per-column enrichment for a table."""

    enrichments: list[ColumnEnrichment]


_SYSTEM_PROMPT = """\
You are a DataOps expert classifying database columns for an automated schema-mapping \
system. For each column, choose the ONE `inferred_semantic_type` from the allowed enum \
that best describes what kind of business data the column holds (email address, \
person name, currency amount, date, etc.) — NOT just the raw SQL type. When ambiguous, \
prefer the more specific enum. Emit a calibrated `semantic_type_confidence` (0-1).

Also emit `quality_flags` — any that apply:
- HIGH_NULL_RATE if null_rate > 0.5
- LOW_CARDINALITY if distinct_count / total_count < 0.01 (and total_count > 100)
- SUSPECT_PII if the column name or values suggest personally identifiable information
- NO_DESCRIPTION if ms_description is null/empty
- AMBIGUOUS_TYPE if the column name + type + samples don't clearly indicate one semantic type

If `ms_description` is null/empty, ALSO generate `generated_description`: a concise 1-2 sentence \
description of what business data the column holds, in the dimensional/fact context of its table \
(e.g., for `dbo.FactInternetSales.SalesAmount` say "Total dollar amount of the sale per line item, \
unit price times quantity less discounts" — describe the column's role, not just the SQL type). \
If `ms_description` is already populated, return null for `generated_description`.

Be literal about the data. Don't guess beyond what the column name, type, description, \
table context, and top sample values show."""


def _user_prompt_for_table(table: TableProfile) -> str:
    """Render a compact table description for the LLM."""
    header = f"Database table: {table.table_schema}.{table.table_name}"
    if table.ms_description:
        header += f"\nTable description: {table.ms_description}"
    header += f"\nRow count estimate: {table.row_count_estimate}"
    header += f"\nPrimary key: {table.primary_key}"
    if table.foreign_keys:
        fks = "; ".join(f"{fk['from']} -> {fk['to']}" for fk in table.foreign_keys)
        header += f"\nForeign keys: {fks}"

    lines = [header, "", "Columns (one per line):"]
    for c in table.columns:
        parts = [
            f"- name={c.column_name}",
            f"type={c.sql_type}",
            f"nullable={c.is_nullable}",
            f"pk={c.is_primary_key}",
            f"fk={c.is_foreign_key}",
        ]
        if c.fk_ref:
            parts.append(f"fk_ref={c.fk_ref}")
        if c.total_count:
            parts.append(f"null_rate={c.null_rate:.3f}")
            parts.append(f"distinct={c.distinct_count}/{c.total_count}")
        if c.top_values:
            samples = ", ".join(repr(v) for v, _ in c.top_values[:3])
            parts.append(f"top={samples}")
        if c.ms_description:
            parts.append(f'desc="{c.ms_description[:80]}"')
        lines.append("  ".join(parts))

    lines.append("")
    lines.append("Return enrichments IN THE SAME ORDER as the columns above, one per column.")
    return "\n".join(lines)


def enrich_schema(
    profile: SchemaProfile,
    llm: LLMClient,
    *,
    only_tables: list[tuple[str, str]] | None = None,
    rate_limit_delay_sec: float = 0.0,
) -> SchemaProfile:
    """Enrich every table's columns in `profile` via the LLM. Mutates + returns the profile.

    only_tables: when set, restrict enrichment to the given (schema, table) pairs.
        The SchemaProfile itself still contains every table, so downstream mapping
        can still see un-enriched tables — they just keep inferred_semantic_type=UNKNOWN.
    rate_limit_delay_sec: sleep between LLM calls to stay under provider RPM limits.
        Default 0.0 (no sleep); bump to e.g. 6.5 for Gemini Flash free tier (10 RPM) when
        you expect many cache misses. Cache-hit calls are skipped transparently because
        they don't touch the network.
    """
    allowed: set[tuple[str, str]] | None = set(only_tables) if only_tables else None

    total = (
        len(profile.tables)
        if allowed is None
        else sum(1 for t in profile.tables if (t.table_schema, t.table_name) in allowed)
    )

    idx = 0
    for table in profile.tables:
        if allowed is not None and (table.table_schema, table.table_name) not in allowed:
            continue
        idx += 1
        log.info(
            "schema_explorer %d/%d: %s.%s",
            idx,
            total,
            table.table_schema,
            table.table_name,
        )
        made_call = _enrich_one_table(table, llm)
        if made_call and rate_limit_delay_sec > 0 and idx < total:
            time.sleep(rate_limit_delay_sec)
    return profile


def _enrich_one_table(table: TableProfile, llm: LLMClient) -> bool:
    """Send one structured-output call; fold results into `table.columns` in place.

    Returns True iff a network call to the provider was made (i.e. cache miss).
    Callers can use this to skip rate-limit sleeps on cache-hit paths.
    """
    if not table.columns:
        return False

    user_prompt = _user_prompt_for_table(table)

    # Peek cache to decide whether we'll hit the network
    from agents.llm import get_cached, prompt_cache_key

    cache_key = prompt_cache_key(
        llm.provider, llm.model, _SYSTEM_PROMPT, user_prompt, TableEnrichment.__name__
    )
    cache_hit = get_cached(cache_key) is not None

    try:
        result = llm.structured(_SYSTEM_PROMPT, user_prompt, TableEnrichment)
    except Exception as exc:  # noqa: BLE001
        log.warning("enrichment failed for %s.%s: %s", table.table_schema, table.table_name, exc)
        return not cache_hit

    by_name = {e.column_name: e for e in result.enrichments}
    for col in table.columns:
        e = by_name.get(col.column_name)
        if e is None:
            continue
        col.inferred_semantic_type = e.inferred_semantic_type
        col.semantic_type_confidence = e.semantic_type_confidence
        col.quality_flags = e.quality_flags
        # Only fill ms_description from LLM if the source DB didn't have one — never overwrite.
        if e.generated_description and not col.ms_description:
            col.ms_description = e.generated_description
    return not cache_hit
