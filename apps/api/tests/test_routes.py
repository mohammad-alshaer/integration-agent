"""Route-level tests for /health, /map, /eval. All offline (FakeLLM + ConstantEmbedder)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from schemas import SchemaProfile


def _map_body(
    source: SchemaProfile,
    target: SchemaProfile,
    *,
    target_table: str = "dbo.DimCustomer",
    sample_dir: str | None = None,
    rebuild_index: bool = False,
) -> dict:
    return {
        "source_profile": source.model_dump(mode="json"),
        "target_profile": target.model_dump(mode="json"),
        "target_table": target_table,
        "k_candidates": 5,
        "max_retries": 1,
        "rebuild_index": rebuild_index,
        "sample_dir": sample_dir,
    }


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "fake"
    assert body["llm_model"] == "fake-1"
    assert body["embedder_provider"] == "fake"
    assert body["embedder_dims"] == 16
    assert body["deep_check"] is None


def test_health_deep_passes(client: TestClient, api_deps) -> None:
    # SmokeFakeLLM only handles MatcherOutput / ClassifierOutput / DerivedSpec,
    # so a generic _DeepEcho probe will raise. The endpoint surfaces that as
    # deep_check.ok=false rather than 500 — which is the correct behavior.
    r = client.get("/health?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["deep_check"] is not None
    assert "llm_round_trip_ms" in body["deep_check"]


def test_map_happy_path_no_sandbox(
    client: TestClient,
    smoke_source: SchemaProfile,
    smoke_target: SchemaProfile,
) -> None:
    r = client.post("/map", json=_map_body(smoke_source, smoke_target))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_table"] == "dbo.DimCustomer"
    assert len(body["specs"]) >= 3  # Rename + Concat + (Derived may pass through)
    assert body["validation_summary"] is None
    assert body["retry_count"] == 0
    assert body["elapsed_sec"] > 0
    patterns = body["classifications_summary"]
    assert patterns.get("rename", 0) >= 2
    assert patterns.get("concat", 0) >= 1


def test_map_with_sandbox_runs_validator(
    client: TestClient,
    smoke_source: SchemaProfile,
    smoke_target: SchemaProfile,
    smoke_sample_dir: Path,
) -> None:
    r = client.post(
        "/map",
        json=_map_body(smoke_source, smoke_target, sample_dir=str(smoke_sample_dir)),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_summary"] is not None
    assert body["validation_summary"]["passed"] >= 1
    # Smoke FakeLLM emits broken DERIVED on first attempt, corrected on retry
    assert body["retry_count"] == 1


def test_map_unknown_target_table_404(
    client: TestClient,
    smoke_source: SchemaProfile,
    smoke_target: SchemaProfile,
) -> None:
    r = client.post(
        "/map",
        json=_map_body(smoke_source, smoke_target, target_table="dbo.DoesNotExist"),
    )
    assert r.status_code == 404


def test_map_validation_error_422(
    client: TestClient,
    smoke_source: SchemaProfile,
    smoke_target: SchemaProfile,
) -> None:
    body = _map_body(smoke_source, smoke_target)
    body.pop("target_table")
    r = client.post("/map", json=body)
    assert r.status_code == 422


def _write_synthetic_report(reports_dir: Path, *, run_id: str, pair: str = "smoke") -> Path:
    out = reports_dir / pair / "out"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "eval_report.json"
    path.write_text(
        json.dumps(
            {
                "pair": pair,
                "provider": "fake",
                "model": "fake-1",
                "run_id": run_id,
                "ran_at": datetime.now(UTC).isoformat(),
                "expected_count": 4,
                "actual_count": 4,
                "exact_match_count": 3,
                "pattern_match_count": 1,
                "sql_exec_equivalent_match_count": 0,
                "sql_semantic_match_count": 0,
                "missing_count": 0,
                "extra_count": 0,
                "mismatch_count": 0,
                "rates": {
                    "inclusive": {"exact": 0.75, "pattern": 1.0},
                    "exclusive": {"exact": 0.75, "pattern": 1.0},
                },
                "per_pattern": {},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_eval_endpoints(client: TestClient, api_deps) -> None:
    reports_dir = api_deps.settings.reports_dir
    _write_synthetic_report(reports_dir, run_id="20260101-120000")

    r = client.get("/eval")
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    assert summaries[0]["run_id"] == "20260101-120000"
    assert summaries[0]["pair"] == "smoke"
    assert summaries[0]["exact_match_rate_inclusive"] == 0.75

    r = client.get("/eval/20260101-120000")
    assert r.status_code == 200
    assert r.json()["run_id"] == "20260101-120000"

    r = client.get("/eval/does-not-exist")
    assert r.status_code == 404
