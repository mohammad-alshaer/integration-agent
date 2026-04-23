"""Column-name based PII redaction for sample rows before Parquet export.

Strategy: if a column name matches a PII-shaped pattern (Email, Phone, CreditCard,
Password, SSN), replace each value with a deterministic short hash. Preserves
distinctness (group-by / join keys still work in the sandbox) while hiding the
actual content. For M1 this is sufficient. We can get fancier (format-preserving
fake generators) later if real sample data demands it.

Usage:
    from sqlserver.redaction import mask_dataframe, is_pii_column
    df = mask_dataframe(df, columns=[c for c in df.columns if is_pii_column(c)])
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

import pandas as pd

# Case-insensitive regex. Matches substrings so e.g. EmailAddress, PrimaryPhone,
# CreditCardNumber, PasswordHash, SocialSecurityNumber, SSN all match.
PII_COLUMN_PATTERN = re.compile(
    r"(?i)(email|phone|creditcard|password|ssn|socialsecurity)",
)


def is_pii_column(column_name: str) -> bool:
    """Return True if the column name matches a PII-shaped pattern."""
    return bool(PII_COLUMN_PATTERN.search(column_name))


def _mask_value(value: object) -> object:
    """Hash a single value to `REDACTED_<8-char-sha1>`. None stays None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    h = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
    return f"REDACTED_{h}"


def mask_dataframe(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Return a copy of `df` with the named columns hashed. Other columns unchanged."""
    columns = [c for c in columns if c in df.columns]
    if not columns:
        return df
    masked = df.copy()
    for c in columns:
        masked[c] = masked[c].map(_mask_value)
    return masked
