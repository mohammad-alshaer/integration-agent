# ADR 0003 — DuckDB sandbox reads Parquet exports, not SQL Server directly

**Status:** Accepted (2026-04-23)

**Context.** The Validator runs candidate dbt SQL against sample rows to measure pass rates. Source data lives in SQL Server. Two options: (a) connect DuckDB to SQL Server via DuckDB's experimental SQL Server extension, (b) export a bounded sample to Parquet on disk and load that into DuckDB.

**Decision.** Use option (b). Export via `pyodbc → pandas.DataFrame → df.to_parquet()`, then `duckdb.read_parquet()` inside the sandbox. The FK-closure sampler lives in `packages/sqlserver/src/sqlserver/sample.py`; PII-shaped columns are masked in `redaction.py` before the DataFrame ever reaches Parquet.

**Consequences.** (+) Deterministic sandbox state — same Parquet = same run, enables the SHA-256 prompt-hash cache to stay honest. (+) No ODBC in the hot path; validator runs fast and offline. (+) Redaction layer sits at the export step, so PII never appears in traces or sample-row previews. (+) Avoids known breakage of DuckDB's SQL Server extension on AdventureWorks types (`hierarchyid`, `geography`). (−) Samples can go stale — acceptable; for each eval run we regenerate them. Windows dev-only: `TrustServerCertificate=yes` is set on the ODBC connection string; documented here so production deploys know to remove it.
