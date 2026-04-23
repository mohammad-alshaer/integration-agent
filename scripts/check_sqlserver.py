"""Smoke test: connect to local SQLDEV2025 instance and print server version.

Uses Windows auth (Trusted Connection) via ODBC Driver 18.
TrustServerCertificate=yes is fine for local dev (self-signed cert); never use in prod.
"""

from __future__ import annotations

import sys

import pyodbc

CONN_STR = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=localhost\\SQLDEV2025;"
    "Database=master;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def main() -> int:
    try:
        with pyodbc.connect(CONN_STR) as conn:
            cur = conn.cursor()
            cur.execute("SELECT @@VERSION;")
            version = cur.fetchone()[0]
            print(version)

            cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name;")
            user_dbs = [row[0] for row in cur.fetchall()]
            print(f"\nUser databases on this instance: {user_dbs or '(none yet)'}")
    except pyodbc.Error as exc:
        print(f"[check_sqlserver] connection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
