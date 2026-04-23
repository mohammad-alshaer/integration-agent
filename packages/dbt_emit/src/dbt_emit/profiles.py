"""Write profiles.yml — local-dev DuckDB profile for dbt-duckdb.

This is the local profile that lets the generated project build against the
same DuckDB file Integration-Agent's sandbox uses. In CI / prod the user
supplies their own profiles.yml; we don't commit the one we generate here.
"""

from __future__ import annotations

from pathlib import Path


def write_profiles_yml(
    out_dir: Path,
    *,
    profile_name: str = "integration_agent_local",
    duckdb_path: Path,
    threads: int = 4,
) -> Path:
    """Write `profiles.yml` pointing dbt at `duckdb_path`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Forward slashes work on Windows in DuckDB / dbt config.
    duckdb_norm = str(duckdb_path).replace("\\", "/")
    content = (
        f"{profile_name}:\n"
        f"  target: dev\n"
        f"  outputs:\n"
        f"    dev:\n"
        f"      type: duckdb\n"
        f"      path: {duckdb_norm!r}\n"
        f"      threads: {threads}\n"
    )
    path = out_dir / "profiles.yml"
    path.write_text(content, encoding="utf-8")
    return path
