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
from schemas import MappingSpec

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


def classify_match(expected: ExpectedMapping, actual: MappingSpec | None) -> MatchLevel:
    if actual is None:
        return MatchLevel.MISSING
    e_set = frozenset(expected.expected_source_fqns)
    a_set = frozenset(actual.source_fqns)
    if expected.expected_pattern == actual.pattern and e_set == a_set:
        return MatchLevel.EXACT
    if expected.expected_pattern == actual.pattern:
        return MatchLevel.PATTERN
    norm = normalize_sql(actual.sql)
    tokens = {fqn.rsplit(".", 1)[-1] for fqn in expected.expected_source_fqns}
    if tokens and all(re.search(rf"\b{re.escape(t)}\b", norm) for t in tokens):
        return MatchLevel.SQL_SEMANTIC
    return MatchLevel.MISMATCH


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
    """Per-entry match rates across the supplied (already-filtered) list."""
    n = sum(1 for e in entries if e.level != MatchLevel.EXTRA)
    exact = sum(1 for e in entries if e.level == MatchLevel.EXACT)
    pattern_only = sum(1 for e in entries if e.level == MatchLevel.PATTERN)
    sql_semantic = sum(1 for e in entries if e.level == MatchLevel.SQL_SEMANTIC)
    return {
        "exact": _rate(exact, n),
        "pattern": _rate(exact + pattern_only, n),
        "sql_semantic": _rate(exact + pattern_only + sql_semantic, n),
    }


def score(
    expected_file: ExpectedMappingsFile,
    actual_specs: list[MappingSpec],
    *,
    provider: str,
    model: str,
    run_id: str,
) -> EvalReport:
    actual_by_fqn: dict[str, MappingSpec] = {s.target_fqn: s for s in actual_specs}

    entries: list[ScoreEntry] = []
    expected_fqns: set[str] = set()
    for exp in expected_file.mappings:
        expected_fqns.add(exp.target_fqn)
        actual = actual_by_fqn.get(exp.target_fqn)
        level = classify_match(exp, actual)
        entries.append(_build_entry(exp, actual, level))

    for spec in actual_specs:
        if spec.target_fqn not in expected_fqns:
            entries.append(_extra_entry(spec))

    exact_count = sum(1 for e in entries if e.level == MatchLevel.EXACT)
    pattern_only_count = sum(1 for e in entries if e.level == MatchLevel.PATTERN)
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
        entries=entries,
    )


__all__ = ["classify_match", "normalize_sql", "score"]
