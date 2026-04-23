"""Internal utilities shared across sqlserver modules."""

from __future__ import annotations


def quote_ident(identifier: str) -> str:
    """Bracket-quote a SQL Server identifier (escapes embedded `]`)."""
    return f"[{identifier.replace(']', ']]')}]"
