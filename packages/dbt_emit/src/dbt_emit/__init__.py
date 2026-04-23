"""Emit a dbt-duckdb project from a list of MappingSpecs.

M1 layout emitted under `out_dir/`:
    dbt_project.yml
    profiles.yml                                       (local dev; points at a DuckDB file)
    models/staging/stg_<target_table>_from_<source_table>.sql
    models/staging/schema.yml

One `.sql` per (target_table, source_table) pair — keeps each model's FROM clause
to a single source, defers multi-source JOIN stitching to M2. The eval harness
reports per-MappingSpec accuracy regardless of how the specs are grouped into files.
"""

from dbt_emit.emitter import emit_dbt_project
from dbt_emit.model import write_models
from dbt_emit.profiles import write_profiles_yml
from dbt_emit.project import write_project_yml
from dbt_emit.schema_yml import write_schema_yml

__all__ = [
    "emit_dbt_project",
    "write_models",
    "write_profiles_yml",
    "write_project_yml",
    "write_schema_yml",
]
