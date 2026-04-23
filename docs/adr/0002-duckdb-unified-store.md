# ADR 0002 — DuckDB + vss as the unified metadata + vector store

**Status:** Accepted (2026-04-23). **Supersedes:** original plan's Postgres 16 + pgvector.

**Context.** The plan originally specified Postgres 16 + pgvector to store mappings, embeddings, and feedback under a single transactional store. Running Postgres locally required Docker Desktop or equivalent. Mohammad's Dar-managed Windows 11 machine has corporate AppLocker + licensing policies that block Docker Desktop, WSL, and Podman without admin + IT approval — a multi-day blocker.

**Decision.** Use DuckDB as the unified metadata + vector store via its `vss` extension (HNSW index + `array_distance`). Single-file, in-process, AppLocker-safe. One engine now covers three roles: (1) sandbox for transformation validation, (2) metadata store for projects / mappings / runs, (3) vector store for Voyage embeddings used by the Semantic Matcher.

**Consequences.** (+) No infrastructure to install or license. (+) One less moving part; lower architectural surface area. (+) Deterministic, easy to back up (single file), trivial to reset for tests. (−) Single-process — fine for M1-M2 CLI; revisit for M3 FastAPI when multiple workers may hit the same file. Options at that point: serialize DB access through a connection manager, switch to SQLite WAL, or finally install native Postgres / use SQL Server 2025's built-in VECTOR type. (−) Less "production-representative." For the CIO showcase we frame this as a feature: "same engine for sandbox, metadata, and vectors — nothing to provision."
