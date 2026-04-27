"""GET /eval — list summaries; GET /eval/{run_id} — full report by run_id."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.deps import ApiDeps, get_deps
from api.eval_lookup import find_report_by_run_id, list_reports
from evals.models import EvalReport
from schemas import EvalSummary

router = APIRouter(prefix="/eval")


def _to_summary(path: Path, r: EvalReport) -> EvalSummary:
    inclusive = r.rates.get("inclusive", {})
    exclusive = r.rates.get("exclusive", {})
    return EvalSummary(
        run_id=r.run_id,
        pair=r.pair,
        provider=r.provider,
        model=r.model,
        ran_at=r.ran_at,
        expected_count=r.expected_count,
        exact_match_rate_inclusive=float(inclusive.get("exact", 0.0)),
        exact_match_rate_exclusive=float(exclusive.get("exact", 0.0)),
        pipeline_dollars_total=r.pipeline_dollars_total,
        report_path=str(path),
    )


@router.get("", response_model=list[EvalSummary])
async def list_eval_reports(deps: ApiDeps = Depends(get_deps)) -> list[EvalSummary]:
    return [_to_summary(p, r) for p, r in list_reports(deps.settings.reports_dir)]


@router.get("/{run_id}", response_model=EvalReport)
async def get_eval_report(run_id: str, deps: ApiDeps = Depends(get_deps)) -> EvalReport:
    found = find_report_by_run_id(run_id, deps.settings.reports_dir)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no eval report with run_id={run_id!r}")
    _, report = found
    return report
