"""Scorer tests — match levels, per-pattern breakdown, disputed filter, SQL normalization."""

from __future__ import annotations

import pytest

from evals import classify_match, normalize_sql, score
from evals.models import (
    ExpectedAlternative,
    ExpectedMapping,
    ExpectedMappingsFile,
    MatchLevel,
)
from schemas import DbtTest, MappingSpec, Pattern


def _spec(
    target_fqn: str,
    source_fqns: list[str],
    pattern: Pattern,
    sql: str,
    *,
    llm_conf: float = 0.9,
    pass_rate: float | None = 1.0,
    tests: list[DbtTest] | None = None,
) -> MappingSpec:
    s = MappingSpec(
        target_fqn=target_fqn,
        source_fqns=source_fqns,
        pattern=pattern,
        sql=sql,
        rationale="test",
        tests=tests or [],
        llm_confidence=llm_conf,
    )
    s.validation_pass_rate = pass_rate
    return s


def _expected(
    target_fqn: str,
    pattern: Pattern,
    source_fqns: list[str],
    *,
    disputed: bool = False,
) -> ExpectedMapping:
    return ExpectedMapping(
        target_fqn=target_fqn,
        expected_pattern=pattern,
        expected_source_fqns=source_fqns,
        disputed=disputed,
    )


def _file(*mappings: ExpectedMapping) -> ExpectedMappingsFile:
    return ExpectedMappingsFile(
        pair="test",
        source_database="s",
        target_database="t",
        mappings=list(mappings),
    )


def _score(exp: ExpectedMappingsFile, actual: list[MappingSpec]):
    return score(exp, actual, provider="fake", model="fake-1", run_id="t1")


# ---------- normalize_sql ----------


def test_normalize_sql_collapses_whitespace() -> None:
    assert normalize_sql("  SELECT   a   AS   b  ") == "SELECT a AS b"


def test_normalize_sql_upcases_keywords() -> None:
    assert normalize_sql("select a as b") == "SELECT a AS b"


def test_normalize_sql_preserves_identifiers_that_contain_keywords() -> None:
    # `As` only matches as a standalone word via \b, so AsOfDate is untouched.
    out = normalize_sql("select AsOfDate as dt")
    assert "AsOfDate" in out
    assert " AS dt" in out


def test_normalize_sql_handles_case_expression() -> None:
    out = normalize_sql("select case when x = 0 then 'a' else 'b' end as col")
    assert out.startswith("SELECT CASE WHEN")
    assert " END AS col" in out


# ---------- classify_match ----------


def test_classify_match_missing_when_actual_none() -> None:
    exp = _expected("dbo.T.c", Pattern.RENAME, ["s.S.c"])
    assert classify_match(exp, None) == MatchLevel.MISSING


def test_classify_match_exact() -> None:
    exp = _expected("dbo.T.c", Pattern.RENAME, ["s.S.c"])
    actual = _spec("dbo.T.c", ["s.S.c"], Pattern.RENAME, "SELECT c AS c")
    assert classify_match(exp, actual) == MatchLevel.EXACT


def test_classify_match_pattern_only_when_sources_differ() -> None:
    exp = _expected("dbo.T.c", Pattern.RENAME, ["s.S.a"])
    actual = _spec("dbo.T.c", ["s.S.b"], Pattern.RENAME, "SELECT b AS c")
    assert classify_match(exp, actual) == MatchLevel.PATTERN


def test_classify_match_sql_semantic_when_pattern_differs_but_sources_in_sql() -> None:
    # expected: derived from a + b; actual: classified as rename but SQL contains both tokens
    exp = _expected("dbo.T.c", Pattern.DERIVED, ["s.S.a", "s.S.b"])
    actual = _spec("dbo.T.c", ["s.S.a"], Pattern.RENAME, "SELECT a + b AS c")
    assert classify_match(exp, actual) == MatchLevel.SQL_SEMANTIC


def test_classify_match_mismatch_when_nothing_lines_up() -> None:
    exp = _expected("dbo.T.c", Pattern.DERIVED, ["s.S.a", "s.S.b"])
    actual = _spec("dbo.T.c", ["s.S.x"], Pattern.RENAME, "SELECT x AS c")
    assert classify_match(exp, actual) == MatchLevel.MISMATCH


# ---------- multi-acceptable goldens (M2.1) ----------


def _expected_with_alts(
    target_fqn: str,
    pattern: Pattern,
    source_fqns: list[str],
    *,
    alternatives: list[tuple[Pattern, list[str], str]],
    disputed: bool = False,
) -> ExpectedMapping:
    return ExpectedMapping(
        target_fqn=target_fqn,
        expected_pattern=pattern,
        expected_source_fqns=source_fqns,
        disputed=disputed,
        accepted_alternatives=[
            ExpectedAlternative(pattern=p, source_fqns=s, reason=r)
            for (p, s, r) in alternatives
        ],
    )


@pytest.mark.parametrize(
    ("actual_pattern", "actual_sources", "expected_level"),
    [
        # Primary form matches → EXACT
        (Pattern.DERIVED, ["s.S.a", "s.S.b"], MatchLevel.EXACT),
        # Alternative form matches → EXACT (the stylistic-equivalent form)
        (Pattern.RENAME, ["s.S.computed_ab"], MatchLevel.EXACT),
        # Neither form matches; pattern differs from primary; SQL doesn't carry expected tokens → MISMATCH
        (Pattern.RENAME, ["s.S.x"], MatchLevel.MISMATCH),
    ],
)
def test_classify_match_accepts_alternatives(
    actual_pattern: Pattern,
    actual_sources: list[str],
    expected_level: MatchLevel,
) -> None:
    exp = _expected_with_alts(
        "dbo.T.c",
        Pattern.DERIVED,
        ["s.S.a", "s.S.b"],
        alternatives=[
            (Pattern.RENAME, ["s.S.computed_ab"], "computed_ab is a persisted column = a + b"),
        ],
    )
    actual = _spec("dbo.T.c", actual_sources, actual_pattern, "SELECT x AS c")
    assert classify_match(exp, actual) == expected_level


# ---------- score — the offline DoD + bucket coverage ----------


def test_smoke_graph_specs_4_of_4_exact() -> None:
    """The CLAUDE.md-called-out W4-C offline DoD: 4/4 exact on the smoke fixture."""
    exp = _file(
        _expected("dbo.DimCustomer.CustomerKey", Pattern.RENAME, ["Sales.Customer.CustomerID"]),
        _expected("dbo.DimCustomer.FirstName", Pattern.RENAME, ["Person.Person.FirstName"]),
        _expected(
            "dbo.DimCustomer.FullName",
            Pattern.CONCAT,
            ["Person.Person.FirstName", "Person.Person.MiddleName", "Person.Person.LastName"],
        ),
        _expected(
            "dbo.DimCustomer.EmailPromotionCategory",
            Pattern.DERIVED,
            ["Person.Person.EmailPromotion"],
        ),
    )
    actual = [
        _spec(
            "dbo.DimCustomer.CustomerKey",
            ["Sales.Customer.CustomerID"],
            Pattern.RENAME,
            "SELECT CustomerID AS CustomerKey",
        ),
        _spec(
            "dbo.DimCustomer.FirstName",
            ["Person.Person.FirstName"],
            Pattern.RENAME,
            "SELECT FirstName AS FirstName",
        ),
        _spec(
            "dbo.DimCustomer.FullName",
            ["Person.Person.FirstName", "Person.Person.MiddleName", "Person.Person.LastName"],
            Pattern.CONCAT,
            "SELECT concat_ws(' ', FirstName, MiddleName, LastName) AS FullName",
        ),
        _spec(
            "dbo.DimCustomer.EmailPromotionCategory",
            ["Person.Person.EmailPromotion"],
            Pattern.DERIVED,
            "SELECT CASE WHEN EmailPromotion = 0 THEN 'None' END AS EmailPromotionCategory",
        ),
    ]
    report = _score(exp, actual)
    assert report.expected_count == 4
    assert report.actual_count == 4
    assert report.exact_match_count == 4
    assert report.pattern_match_count == 0
    assert report.rates["inclusive"]["exact"] == 1.0
    assert report.rates["exclusive"]["exact"] == 1.0
    assert report.per_pattern["rename"]["exact"] == 2
    assert report.per_pattern["concat"]["exact"] == 1
    assert report.per_pattern["derived"]["exact"] == 1


def test_score_missing_bucket() -> None:
    exp = _file(_expected("dbo.T.a", Pattern.RENAME, ["s.S.a"]))
    report = _score(exp, [])
    assert report.missing_count == 1
    assert report.exact_match_count == 0
    assert report.rates["inclusive"]["exact"] == 0.0


def test_score_extra_bucket() -> None:
    exp = _file()
    actual = [_spec("dbo.T.a", ["s.S.a"], Pattern.RENAME, "SELECT a AS a")]
    report = _score(exp, actual)
    assert report.extra_count == 1
    assert report.exact_match_count == 0
    # EXTRA is not counted in rates (zero denominator).
    assert report.rates["inclusive"]["exact"] == 0.0


def test_score_disputed_filter_changes_exclusive_denominator() -> None:
    exp = _file(
        _expected("dbo.T.a", Pattern.RENAME, ["s.S.a"]),
        _expected("dbo.T.b", Pattern.RENAME, ["s.S.b"], disputed=True),
    )
    # Mark a as exact-match, b as mismatch (wrong pattern)
    actual = [
        _spec("dbo.T.a", ["s.S.a"], Pattern.RENAME, "SELECT a AS a"),
        _spec("dbo.T.b", ["s.S.x"], Pattern.DERIVED, "SELECT x AS b"),
    ]
    report = _score(exp, actual)
    # inclusive (2 denom): 1 exact
    assert report.rates["inclusive"]["exact"] == 0.5
    # exclusive (1 denom, the disputed b is excluded): 1 exact of 1
    assert report.rates["exclusive"]["exact"] == 1.0


def test_score_per_pattern_breakdown() -> None:
    exp = _file(
        _expected("dbo.T.a", Pattern.RENAME, ["s.S.a"]),
        _expected("dbo.T.b", Pattern.RENAME, ["s.S.b"]),
        _expected("dbo.T.c", Pattern.CONCAT, ["s.S.c1", "s.S.c2"]),
        _expected("dbo.T.d", Pattern.DERIVED, ["s.S.d"]),
    )
    actual = [
        _spec("dbo.T.a", ["s.S.a"], Pattern.RENAME, "SELECT a AS a"),
        _spec("dbo.T.b", ["s.S.different"], Pattern.RENAME, "SELECT different AS b"),  # PATTERN
        _spec(
            "dbo.T.c", ["s.S.c1", "s.S.c2"], Pattern.CONCAT, "SELECT concat_ws(' ', c1, c2) AS c"
        ),
        # d missing
    ]
    report = _score(exp, actual)
    assert report.per_pattern["rename"] == {
        "expected": 2,
        "exact": 1,
        "pattern_only": 1,
        "sql_semantic": 0,
        "mismatch": 0,
        "missing": 0,
    }
    assert report.per_pattern["concat"]["exact"] == 1
    assert report.per_pattern["derived"]["missing"] == 1


def test_score_aggregates_llm_confidence_and_tokens() -> None:
    exp = _file(_expected("dbo.T.a", Pattern.RENAME, ["s.S.a"]))
    s = _spec("dbo.T.a", ["s.S.a"], Pattern.RENAME, "SELECT a AS a", llm_conf=0.8, pass_rate=0.9)
    s.tokens_in = 100
    s.tokens_out = 50
    s.prompt_cache_hit = True
    report = _score(exp, [s])
    assert report.mean_llm_confidence == 0.8
    assert report.mean_validation_pass_rate == 0.9
    assert report.prompt_cache_hit_rate == 1.0
    assert report.tokens_in_total == 100
    assert report.tokens_out_total == 50


def test_score_pipeline_telemetry_passthrough() -> None:
    """Pipeline-level totals (matcher + classifier + generator) flow into the report."""
    exp = _file(_expected("dbo.T.a", Pattern.RENAME, ["s.S.a"]))
    s = _spec("dbo.T.a", ["s.S.a"], Pattern.RENAME, "SELECT a AS a")
    report = score(
        exp,
        [s],
        provider="fake",
        model="fake-1",
        run_id="t1",
        pipeline_total_llm_calls=80,
        pipeline_total_tokens_in=240_000,
        pipeline_total_tokens_out=40_000,
        pipeline_cache_hit_rate=0.25,
    )
    assert report.pipeline_total_llm_calls == 80
    assert report.pipeline_total_tokens_in == 240_000
    assert report.pipeline_total_tokens_out == 40_000
    assert report.pipeline_cache_hit_rate == 0.25
