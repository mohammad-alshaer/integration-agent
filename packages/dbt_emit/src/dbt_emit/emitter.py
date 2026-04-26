"""Top-level emitter — produces the full dbt project layout from a list of MappingSpecs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dbt_emit.model import write_models
from dbt_emit.profiles import write_profiles_yml
from dbt_emit.project import write_project_yml
from dbt_emit.schema_yml import write_schema_yml
from schemas import MappingSpec, SchemaProfile


@dataclass(frozen=True)
class EmittedProject:
    """Where everything landed."""

    out_dir: Path
    project_yml: Path
    profiles_yml: Path
    schema_yml: Path
    model_files: list[Path]


def emit_dbt_project(
    specs: list[MappingSpec],
    out_dir: Path,
    duckdb_path: Path,
    *,
    project_name: str = "integration_agent_out",
    profile_name: str = "integration_agent_local",
    source_name: str = "aw_oltp",
    source_schema: str = "source_raw",
    run_id: str = "w4b",
    source_profile: SchemaProfile | None = None,
) -> EmittedProject:
    """Emit project.yml + profiles.yml + stg_*.sql files + schema.yml under `out_dir`.

    duckdb_path: the DuckDB file dbt will run against. Must exist and contain the
    `source_schema.<schema>_<table>` views the model SQL references (populated by
    the caller via Sandbox.persist_sources or equivalent).

    source_profile: when supplied, multi-source-table specs become intermediate
    JOIN models (FK looked up via ColumnProfile.fk_ref). Without it, multi-source
    specs fall through to the _unmodeled_multi_source.txt sidecar.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    project_yml = write_project_yml(out_dir, name=project_name, profile=profile_name)
    profiles_yml = write_profiles_yml(out_dir, profile_name=profile_name, duckdb_path=duckdb_path)
    model_files = write_models(
        specs,
        out_dir,
        run_id=run_id,
        source_name=source_name,
        source_profile=source_profile,
    )
    schema_yml = write_schema_yml(
        specs, out_dir, source_name=source_name, source_schema=source_schema
    )

    return EmittedProject(
        out_dir=out_dir,
        project_yml=project_yml,
        profiles_yml=profiles_yml,
        schema_yml=schema_yml,
        model_files=model_files,
    )
