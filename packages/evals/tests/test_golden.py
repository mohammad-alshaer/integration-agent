"""Golden YAML loader tests — round-trip + validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from evals import load_expected
from evals.models import ExpectedMapping, ExpectedMappingsFile
from schemas import Pattern


def _write_yaml(path: Path, data: dict | str) -> Path:
    text = yaml.safe_dump(data) if not isinstance(data, str) else data
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_roundtrip(tmp_path: Path) -> None:
    payload = {
        "pair": "adventureworks",
        "source_database": "AdventureWorks2022",
        "target_database": "AdventureWorksDW2022",
        "mappings": [
            {
                "target_fqn": "dbo.DimCustomer.FirstName",
                "expected_pattern": "rename",
                "expected_source_fqns": ["Person.Person.FirstName"],
                "disputed": False,
            },
            {
                "target_fqn": "dbo.DimCustomer.FullName",
                "expected_pattern": "concat",
                "expected_source_fqns": [
                    "Person.Person.FirstName",
                    "Person.Person.MiddleName",
                    "Person.Person.LastName",
                ],
                "disputed": False,
                "note": "N:1 name parts",
            },
        ],
    }
    path = _write_yaml(tmp_path / "golden.yaml", payload)
    loaded = load_expected(path)

    assert isinstance(loaded, ExpectedMappingsFile)
    assert loaded.pair == "adventureworks"
    assert loaded.source_database == "AdventureWorks2022"
    assert len(loaded.mappings) == 2
    assert loaded.mappings[0].expected_pattern == Pattern.RENAME
    assert loaded.mappings[1].expected_pattern == Pattern.CONCAT
    assert loaded.mappings[1].note == "N:1 name parts"


def test_loader_disputed_defaults_false(tmp_path: Path) -> None:
    payload = {
        "pair": "test",
        "source_database": "s",
        "target_database": "t",
        "mappings": [
            {
                "target_fqn": "t.T.c",
                "expected_pattern": "rename",
                "expected_source_fqns": ["s.S.c"],
            }
        ],
    }
    loaded = load_expected(_write_yaml(tmp_path / "g.yaml", payload))
    assert loaded.mappings[0].disputed is False
    assert loaded.mappings[0].note is None


def test_loader_missing_required_field_raises(tmp_path: Path) -> None:
    payload = {
        "pair": "test",
        "source_database": "s",
        "target_database": "t",
        "mappings": [
            {
                "target_fqn": "t.T.c",
                # missing expected_pattern
                "expected_source_fqns": ["s.S.c"],
            }
        ],
    }
    with pytest.raises(ValidationError):
        load_expected(_write_yaml(tmp_path / "g.yaml", payload))


def test_loader_unknown_pattern_raises(tmp_path: Path) -> None:
    payload = {
        "pair": "test",
        "source_database": "s",
        "target_database": "t",
        "mappings": [
            {
                "target_fqn": "t.T.c",
                "expected_pattern": "fictional_pattern",
                "expected_source_fqns": ["s.S.c"],
            }
        ],
    }
    with pytest.raises(ValidationError):
        load_expected(_write_yaml(tmp_path / "g.yaml", payload))


def test_expected_mapping_construction() -> None:
    m = ExpectedMapping(
        target_fqn="dbo.T.c",
        expected_pattern=Pattern.DERIVED,
        expected_source_fqns=["s.S.c"],
    )
    assert m.disputed is False
    assert m.note is None
