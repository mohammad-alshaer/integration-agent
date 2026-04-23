"""Load hand-authored `expected_mappings.yaml` into a validated Pydantic model."""

from __future__ import annotations

from pathlib import Path

import yaml

from evals.models import ExpectedMappingsFile


def load_expected(path: Path) -> ExpectedMappingsFile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ExpectedMappingsFile.model_validate(raw)
