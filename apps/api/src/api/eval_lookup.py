"""Glob + parse + 60s TTL cache for EvalReport JSON files."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from pydantic import ValidationError

from evals.models import EvalReport

log = logging.getLogger(__name__)

_TTL_SEC = 60.0
_cache: dict[str, tuple[float, list[tuple[Path, EvalReport]]]] = {}


def list_reports(root: Path) -> list[tuple[Path, EvalReport]]:
    """Return (path, report) tuples for every parseable eval_report*.json under root.

    Caches per-root for 60s. N is small (~10), parse cost is microseconds.
    """
    key = str(root.resolve())
    cached = _cache.get(key)
    if cached is not None and (time.monotonic() - cached[0]) < _TTL_SEC:
        return cached[1]

    out: list[tuple[Path, EvalReport]] = []
    if not root.exists():
        _cache[key] = (time.monotonic(), out)
        return out

    for p in sorted(root.glob("*/out/eval_report*.json")):
        try:
            r = EvalReport.model_validate_json(p.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as e:
            log.warning("eval_lookup: skipping %s (%s)", p, e)
            continue
        out.append((p, r))

    _cache[key] = (time.monotonic(), out)
    return out


def find_report_by_run_id(run_id: str, root: Path) -> tuple[Path, EvalReport] | None:
    for path, report in list_reports(root):
        if report.run_id == run_id:
            return path, report
    return None


def invalidate_cache() -> None:
    """For tests. Clear the per-root TTL cache."""
    _cache.clear()
