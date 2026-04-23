"""Runner smoke tests — end-to-end with the fake provider (no network)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml

from evals import RunnerConfig, run_eval
from evals._fakes import (
    build_smoke_source_profile,
    build_smoke_target_profile,
    write_smoke_sample_parquets,
)


def _write_profiles(tmp_path: Path) -> tuple[Path, Path]:
    source = build_smoke_source_profile()
    target = build_smoke_target_profile()
    src_p = tmp_path / "source.json"
    tgt_p = tmp_path / "target.json"
    src_p.write_text(source.model_dump_json(indent=2), encoding="utf-8")
    tgt_p.write_text(target.model_dump_json(indent=2), encoding="utf-8")
    return src_p, tgt_p


def _write_golden(tmp_path: Path) -> Path:
    payload = {
        "pair": "smoke",
        "source_database": "AdventureWorks2022",
        "target_database": "AdventureWorksDW2022",
        "mappings": [
            {
                "target_fqn": "dbo.DimCustomer.CustomerKey",
                "expected_pattern": "rename",
                "expected_source_fqns": ["Sales.Customer.CustomerID"],
            },
            {
                "target_fqn": "dbo.DimCustomer.FirstName",
                "expected_pattern": "rename",
                "expected_source_fqns": ["Person.Person.FirstName"],
            },
            {
                "target_fqn": "dbo.DimCustomer.FullName",
                "expected_pattern": "concat",
                "expected_source_fqns": [
                    "Person.Person.FirstName",
                    "Person.Person.MiddleName",
                    "Person.Person.LastName",
                ],
            },
            {
                "target_fqn": "dbo.DimCustomer.EmailPromotionCategory",
                "expected_pattern": "derived",
                "expected_source_fqns": ["Person.Person.EmailPromotion"],
            },
        ],
    }
    p = tmp_path / "golden.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


def test_run_eval_fake_provider_writes_report(tmp_path: Path) -> None:
    src_p, tgt_p = _write_profiles(tmp_path)
    golden_p = _write_golden(tmp_path)
    out_p = tmp_path / "out" / "eval_report.json"

    sample_dir = Path(tempfile.mkdtemp(prefix="evals_test_samples_"))
    write_smoke_sample_parquets(sample_dir)

    vector_db = tmp_path / "vec.duckdb"

    cfg = RunnerConfig(
        pair="smoke",
        provider="fake",
        model="fake-1",
        source_profile=src_p,
        target_profile=tgt_p,
        golden=golden_p,
        out=out_p,
        vector_db=vector_db,
        sample_dir=sample_dir,
        rate_limit_delay=0.0,
    )
    report = run_eval(cfg)

    assert out_p.exists()
    persisted = json.loads(out_p.read_text(encoding="utf-8"))
    assert persisted["pair"] == "smoke"
    assert persisted["provider"] == "fake"
    assert persisted["expected_count"] == 4

    # The FakeLLM + retry path should land 4/4 exact on the smoke fixture.
    assert report.exact_match_count == 4
    assert report.missing_count == 0
    assert report.rates["inclusive"]["exact"] == 1.0
