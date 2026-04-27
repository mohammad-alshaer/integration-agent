"""Score generated MappingSpecs against hand-authored ExpectedMappings.

Match levels (mutually exclusive per target_fqn):
    EXACT         — pattern + frozenset(sources) identical
    PATTERN       — pattern matches; sources differ
    SQL_SEMANTIC  — pattern differs BUT normalized actual SQL references every expected source column
    MISMATCH      — both present, neither pattern nor SQL_SEMANTIC matches
    MISSING       — expected but no actual
    EXTRA         — actual but no expected

Metrics computed twice: inclusive of `disputed`, and exclusive.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from evals.models import (
    EvalReport,
    ExpectedMapping,
    ExpectedMappingsFile,
    MatchLevel,
    ScoreEntry,
)
from schemas import MappingSpec, Pattern, SchemaProfile

_SQL_KEYWORDS: frozenset[str] = frozenset(
    {
        "SELECT",
        "AS",
        "CAST",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "AND",
        "OR",
        "NOT",
        "NULL",
        "IS",
        "IN",
        "LIKE",
        "BETWEEN",
        "FROM",
        "WHERE",
        "CONCAT_WS",
        "CONCAT",
        "COALESCE",
        "COUNT",
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "DISTINCT",
        "GROUP",
        "BY",
        "ORDER",
        "ON",
        "JOIN",
        "LEFT",
        "RIGHT",
        "INNER",
        "OUTER",
        "WITH",
        "TRUE",
        "FALSE",
        "VARCHAR",
        "INT",
        "FLOAT",
        "DOUBLE",
        "DATE",
        "TIMESTAMP",
    }
)


def normalize_sql(sql: str) -> str:
    """Whitespace + keyword-case normalization. Commutative-arg sorting is deferred to M2."""
    s = " ".join(sql.split())
    for kw in _SQL_KEYWORDS:
        s = re.sub(rf"\b{kw}\b", kw, s, flags=re.IGNORECASE)
    return s.strip().rstrip(";")


def classify_match(
    expected: ExpectedMapping,
    actual: MappingSpec | None,
    *,
    sandbox=None,
    source_profile: SchemaProfile | None = None,
) -> MatchLevel:
    if actual is None:
        return MatchLevel.MISSING
    a_set = frozenset(actual.source_fqns)
    # EXACT can match either the primary expected form OR any accepted alternative
    # (semantically-equivalent stylistic variant). Only EXACT is widened — PATTERN /
    # SQL_EXEC_EQUIVALENT / SQL_SEMANTIC / MISMATCH are measured against the primary so
    # per-pattern bucket counts stay honest.
    forms = [(expected.expected_pattern, frozenset(expected.expected_source_fqns))]
    forms += [(alt.pattern, frozenset(alt.source_fqns)) for alt in expected.accepted_alternatives]
    for pat, src_set in forms:
        if actual.pattern == pat and a_set == src_set:
            return MatchLevel.EXACT
    # SQL_EXEC_EQUIVALENT: executing both canonical (built from expected) and actual SQL
    # yields the same result rows. Truer signal than PATTERN (which only checks the pattern
    # enum) or SQL_SEMANTIC (which only checks token containment). Checked BEFORE PATTERN
    # so it can upgrade a "same pattern, different source" case to a stronger semantic match.
    # Only fires when sandbox is supplied AND validation passed AND the expected pattern has
    # a canonical-SQL synthesis (RENAME or CONCAT — DERIVED has no canonical form in the golden).
    if sandbox is not None and actual.validation_pass_rate == 1.0:
        if _exec_results_equal(expected, actual, sandbox, source_profile):
            return MatchLevel.SQL_EXEC_EQUIVALENT
    if expected.expected_pattern == actual.pattern:
        return MatchLevel.PATTERN
    norm = normalize_sql(actual.sql)
    tokens = {fqn.rsplit(".", 1)[-1] for fqn in expected.expected_source_fqns}
    if tokens and all(re.search(rf"\b{re.escape(t)}\b", norm) for t in tokens):
        return MatchLevel.SQL_SEMANTIC
    return MatchLevel.MISMATCH


def _build_canonical_sql(expected: ExpectedMapping, sandbox) -> tuple[str, str] | None:
    """For RENAME/CONCAT, build (canonical_sql, view_name). Returns None for DERIVED."""
    if not expected.expected_source_fqns:
        return None
    tables = {tuple(fqn.split(".")[:2]) for fqn in expected.expected_source_fqns}
    if len(tables) != 1:
        return None  # multi-table canonical synthesis not in M2.4 scope
    (schema, table) = next(iter(tables))
    view = sandbox.view_for(schema, table) if hasattr(sandbox, "view_for") else None
    if view is None:
        return None
    if expected.expected_pattern == Pattern.RENAME and len(expected.expected_source_fqns) == 1:
        col = expected.expected_source_fqns[0].rsplit(".", 1)[-1]
        return (f"SELECT {col}", view)
    if expected.expected_pattern == Pattern.CONCAT and len(expected.expected_source_fqns) >= 2:
        cols = [fqn.rsplit(".", 1)[-1] for fqn in expected.expected_source_fqns]
        return (f"SELECT concat_ws(' ', {', '.join(cols)})", view)
    return None


def _exec_results_equal(
    expected: ExpectedMapping,
    actual: MappingSpec,
    sandbox,
    source_profile: SchemaProfile | None,
    row_limit: int = 100,
) -> bool:
    """Run both canonical and actual SQL, compare result rows."""
    canonical = _build_canonical_sql(expected, sandbox)
    if canonical is None:
        return False
    canonical_sql, canonical_view = canonical
    try:
        canonical_rows = sandbox.con.execute(
            f"{canonical_sql} FROM {canonical_view} LIMIT {row_limit}"
        ).fetchall()
    except Exception:
        return False
    # Reuse the validator's resolver for the actual SQL — it handles single-table + JOIN.
    from validator.runner import _resolve_from

    fc = _resolve_from(actual, sandbox, source_profile)
    if not fc.resolved:
        return False
    try:
        actual_rows = sandbox.con.execute(
            f"{actual.sql} FROM {fc.view} LIMIT {row_limit}"
        ).fetchall()
    except Exception:
        return False
    # Sort both for stable comparison (DuckDB row order isn't guaranteed across queries).
    return sorted(map(repr, canonical_rows)) == sorted(map(repr, actual_rows))


def _build_entry(
    expected: ExpectedMapping, actual: MappingSpec | None, level: MatchLevel
) -> ScoreEntry:
    return ScoreEntry(
        target_fqn=expected.target_fqn,
        expected_pattern=expected.expected_pattern,
        actual_pattern=actual.pattern if actual is not None else None,
        level=level,
        disputed=expected.disputed,
        expected_source_fqns=list(expected.expected_source_fqns),
        actual_source_fqns=list(actual.source_fqns) if actual is not None else [],
        actual_sql=actual.sql if actual is not None else None,
        actual_llm_confidence=actual.llm_confidence if actual is not None else None,
        actual_validation_pass_rate=actual.validation_pass_rate if actual is not None else None,
    )


def _extra_entry(actual: MappingSpec) -> ScoreEntry:
    return ScoreEntry(
        target_fqn=actual.target_fqn,
        expected_pattern=None,
        actual_pattern=actual.pattern,
        level=MatchLevel.EXTRA,
        disputed=False,
        expected_source_fqns=[],
        actual_source_fqns=list(actual.source_fqns),
        actual_sql=actual.sql,
        actual_llm_confidence=actual.llm_confidence,
        actual_validation_pass_rate=actual.validation_pass_rate,
    )


def _rate(num: int, den: int) -> float:
    return 0.0 if den == 0 else num / den


def _compute_rates(entries: list[ScoreEntry]) -> dict[str, float]:
    """Per-entry match rates across the supplied (already-filtered) list. Cumulative."""
    n = sum(1 for e in entries if e.level != MatchLevel.EXTRA)
    exact = sum(1 for e in entries if e.level == MatchLevel.EXACT)
    pattern_only = sum(1 for e in entries if e.level == MatchLevel.PATTERN)
    sql_exec = sum(1 for e in entries if e.level == MatchLevel.SQL_EXEC_EQUIVALENT)
    sql_semantic = sum(1 for e in entries if e.level == MatchLevel.SQL_SEMANTIC)
    return {
        "exact": _rate(exact, n),
        "pattern": _rate(exact + pattern_only, n),
        "sql_exec_equivalent": _rate(exact + pattern_only + sql_exec, n),
        "sql_semantic": _rate(exact + pattern_only + sql_exec + sql_semantic, n),
    }


def score(
    expected_file: ExpectedMappingsFile,
    actual_specs: list[MappingSpec],
    *,
    provider: str,
    model: str,
    run_id: str,
    pipeline_total_llm_calls: int = 0,
    pipeline_total_tokens_in: int = 0,
    pipeline_total_tokens_out: int = 0,
    pipeline_cache_hit_rate: float | None = None,
    sandbox=None,
    source_profile: SchemaProfile | None = None,
) -> EvalReport:
    actual_by_fqn: dict[str, MappingSpec] = {s.target_fqn: s for s in actual_specs}

    entries: list[ScoreEntry] = []
    expected_fqns: set[str] = set()
    for exp in expected_file.mappings:
        expected_fqns.add(exp.target_fqn)
        actual = actual_by_fqn.get(exp.target_fqn)
        level = classify_match(exp, actual, sandbox=sandbox, source_profile=source_profile)
        entries.append(_build_entry(exp, actual, level))

    for spec in actual_specs:
        if spec.target_fqn not in expected_fqns:
            entries.append(_extra_entry(spec))

    exact_count = sum(1 for e in entries if e.level == MatchLevel.EXACT)
    pattern_only_count = sum(1 for e in entries if e.level == MatchLevel.PATTERN)
    sql_exec_equivalent_count = sum(
        1 for e in entries if e.level == MatchLevel.SQL_EXEC_EQUIVALENT
    )
    sql_semantic_count = sum(1 for e in entries if e.level == MatchLevel.SQL_SEMANTIC)
    mismatch_count = sum(1 for e in entries if e.level == MatchLevel.MISMATCH)
    missing_count = sum(1 for e in entries if e.level == MatchLevel.MISSING)
    extra_count = sum(1 for e in entries if e.level == MatchLevel.EXTRA)

    non_extra = [e for e in entries if e.level != MatchLevel.EXTRA]
    non_extra_non_disputed = [e for e in non_extra if not e.disputed]
    rates = {
        "inclusive": _compute_rates(non_extra),
        "exclusive": _compute_rates(non_extra_non_disputed),
    }

    per_pattern: dict[str, dict[str, int]] = {}
    for e in non_extra:
        key = e.expected_pattern.value if e.expected_pattern is not None else "unknown"
        bucket = per_pattern.setdefault(
            key,
            {
                "expected": 0,
                "exact": 0,
                "pattern_only": 0,
                "sql_exec_equivalent": 0,
                "sql_semantic": 0,
                "mismatch": 0,
                "missing": 0,
            },
        )
        bucket["expected"] += 1
        if e.level == MatchLevel.EXACT:
            bucket["exact"] += 1
        elif e.level == MatchLevel.PATTERN:
            bucket["pattern_only"] += 1
        elif e.level == MatchLevel.SQL_EXEC_EQUIVALENT:
            bucket["sql_exec_equivalent"] += 1
        elif e.level == MatchLevel.SQL_SEMANTIC:
            bucket["sql_semantic"] += 1
        elif e.level == MatchLevel.MISMATCH:
            bucket["mismatch"] += 1
        elif e.level == MatchLevel.MISSING:
            bucket["missing"] += 1

    confidences = [s.llm_confidence for s in actual_specs]
    mean_llm_confidence = (sum(confidences) / len(confidences)) if confidences else None
    pass_rates = [
        s.validation_pass_rate for s in actual_specs if s.validation_pass_rate is not None
    ]
    mean_validation_pass_rate = (sum(pass_rates) / len(pass_rates)) if pass_rates else None
    cache_hits = sum(1 for s in actual_specs if s.prompt_cache_hit)
    prompt_cache_hit_rate = (cache_hits / len(actual_specs)) if actual_specs else None
    tokens_in_total = sum(s.tokens_in for s in actual_specs)
    tokens_out_total = sum(s.tokens_out for s in actual_specs)

    return EvalReport(
        pair=expected_file.pair,
        provider=provider,
        model=model,
        run_id=run_id,
        ran_at=datetime.now(UTC),
        expected_count=len(expected_file.mappings),
        actual_count=len(actual_specs),
        exact_match_count=exact_count,
        pattern_match_count=pattern_only_count,
        sql_exec_equivalent_match_count=sql_exec_equivalent_count,
        sql_semantic_match_count=sql_semantic_count,
        missing_count=missing_count,
        extra_count=extra_count,
        mismatch_count=mismatch_count,
        rates=rates,
        per_pattern=per_pattern,
        mean_llm_confidence=mean_llm_confidence,
        mean_validation_pass_rate=mean_validation_pass_rate,
        prompt_cache_hit_rate=prompt_cache_hit_rate,
        tokens_in_total=tokens_in_total,
        tokens_out_total=tokens_out_total,
        pipeline_total_llm_calls=pipeline_total_llm_calls,
        pipeline_total_tokens_in=pipeline_total_tokens_in,
        pipeline_total_tokens_out=pipeline_total_tokens_out,
        pipeline_cache_hit_rate=pipeline_cache_hit_rate,
        entries=entries,
    )


__all__ = ["classify_match", "normalize_sql", "score"]
