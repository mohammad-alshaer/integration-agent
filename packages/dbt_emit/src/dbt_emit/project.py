"""Write dbt_project.yml."""

from __future__ import annotations

from pathlib import Path

_PROJECT_YML = """\
name: {name!r}
version: "1.0.0"
config-version: 2
profile: {profile!r}
model-paths: ["models"]
test-paths: ["tests"]
target-path: "target"
clean-targets: ["target", "dbt_packages"]

models:
  {name}:
    staging:
      +materialized: view
      +schema: staging
"""


def write_project_yml(
    out_dir: Path,
    *,
    name: str = "integration_agent_out",
    profile: str = "integration_agent_local",
) -> Path:
    """Write `dbt_project.yml` into `out_dir`, returning its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "dbt_project.yml"
    path.write_text(_PROJECT_YML.format(name=name, profile=profile), encoding="utf-8")
    return path
