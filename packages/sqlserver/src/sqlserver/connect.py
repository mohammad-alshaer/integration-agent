"""Centralized pyodbc connection string + connection factory.

All SQL Server connections in this project go through here so we have one place
to tweak driver version, auth mode, TLS posture, or the instance name.
"""

from __future__ import annotations

import os

import pyodbc

DEFAULT_INSTANCE = os.environ.get("SQLSERVER_INSTANCE", "localhost\\SQLDEV2025")
DEFAULT_DRIVER = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server")


def connection_string(
    database: str, *, instance: str | None = None, driver: str | None = None
) -> str:
    """Build a Windows-auth connection string for local dev.

    TrustServerCertificate=yes is OK for local dev (self-signed cert). Never use in production —
    a real cert chain must validate.
    """
    return (
        f"Driver={{{driver or DEFAULT_DRIVER}}};"
        f"Server={instance or DEFAULT_INSTANCE};"
        f"Database={database};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )


def connect(
    database: str, *, instance: str | None = None, driver: str | None = None
) -> pyodbc.Connection:
    """Open a pyodbc connection against the given database on the local instance."""
    return pyodbc.connect(connection_string(database, instance=instance, driver=driver))
