"""SQL Server introspection + sampling + PII redaction for Integration-Agent.

Entry points:
  - `sqlserver.connect.connect(db)`           open a pyodbc connection with Windows auth + TLS-trust-for-dev
  - `sqlserver.introspect.introspect_schema(conn, db)` produce raw SchemaProfile (no stats)
  - `sqlserver.profile_stats.profile_tables(conn, profile)` fill null_rate / distinct / top_values / min / max in-place
  - `sqlserver.sample.sample_to_parquet(conn, db, out_dir, table_fqns, ...)` FK-closure sampler to Parquet
  - `sqlserver.redaction.mask_dataframe(df, columns)` apply PII redaction before Parquet export
"""

from sqlserver.connect import connect, connection_string
from sqlserver.introspect import introspect_schema
from sqlserver.profile_stats import profile_tables
from sqlserver.redaction import PII_COLUMN_PATTERN, is_pii_column, mask_dataframe
from sqlserver.sample import sample_to_parquet

__all__ = [
    "PII_COLUMN_PATTERN",
    "connect",
    "connection_string",
    "introspect_schema",
    "is_pii_column",
    "mask_dataframe",
    "profile_tables",
    "sample_to_parquet",
]
