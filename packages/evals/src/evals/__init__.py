"""Evals package — golden-set scorer + runner for Integration-Agent mappings."""

from evals.golden import load_expected
from evals.models import (
    EvalReport,
    ExpectedMapping,
    ExpectedMappingsFile,
    MatchLevel,
    ScoreEntry,
)
from evals.runner import RunnerConfig, run_eval
from evals.scorer import classify_match, normalize_sql, score

__all__ = [
    "EvalReport",
    "ExpectedMapping",
    "ExpectedMappingsFile",
    "MatchLevel",
    "RunnerConfig",
    "ScoreEntry",
    "classify_match",
    "load_expected",
    "normalize_sql",
    "run_eval",
    "score",
]
