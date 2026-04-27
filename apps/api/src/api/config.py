"""Pydantic-settings config for the API process."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment + .env. Override via `INTEGRATION_AGENT_API_*` env vars."""

    model_config = SettingsConfigDict(env_prefix="INTEGRATION_AGENT_API_", extra="ignore")

    vector_db_path: Path = Path(".duckdb/integration_agent.duckdb")
    reports_dir: Path = Path("benchmarks")
    map_timeout_sec: float = 600.0
    cors_origin: str = "http://localhost:3000"
