# Integration-Agent

A multi-agent AI system that automates the manual, error-prone work of mapping an OLTP source schema to an analytical-warehouse target schema. Given a source database (e.g. SQL Server `AdventureWorks2022`) and a target warehouse (e.g. `AdventureWorksDW2022`), the agents profile both, retrieve candidate sources for each target column, classify the transformation pattern, generate dbt model SQL, validate it against real sample data in a DuckDB sandbox, retry on failure with structured error hints, and emit a runnable dbt project — with confidence and pass-rate metadata on every output column.

Built as a personal portfolio project by Mohammad Falshaer (DataOps engineer, Dar Al-Handasah).

## M1 results — AdventureWorks benchmark

| Metric | Inclusive (38 targets) | Exclusive of disputed |
|---|---|---|
| Exact match | **65.8%** | **83.3%** |
| Pattern match (right transform, different sources) | 73.7% | 93.3% |
| SQL semantic match | 76.3% | 93.3% |

Hand-authored ground truth lives at [`benchmarks/adventureworks/expected_mappings.yaml`](benchmarks/adventureworks/expected_mappings.yaml) (40 entries across `DimCustomer`, `DimProduct`, `FactInternetSales`; ~1/4 flagged `disputed: true` where MS docs are ambiguous).

Per-pattern: RENAME 25/30 exact (the bread-and-butter case is essentially solved). DERIVED 0/8 exact — the model classifies arithmetic columns (`ExtendedAmount`, `DiscountAmount`) as RENAME instead of recognizing the underlying multiplication. M2 prompt work targets exactly this gap.

Run cost: **~$0.30 per full benchmark** on Gemini 2.5 Flash (paid tier-1, 1000 RPM). Wall-clock ~9 min for 38 targets × matcher + classifier + retry-aware generator.

## Architecture

```
                           +------------------+
   SQL Server profile ---> |  Schema Explorer | --> enriched SchemaProfile
                           +------------------+
                                    |
                                    v
   target column -------> +------------------+
                          | Semantic Matcher |     RAG over DuckDB+vss
                          +------------------+     (top-K source candidates)
                                    |
                                    v
                          +-------------------+
                          | Pattern Classifier|     RENAME / CONCAT / DERIVED /
                          +-------------------+     UNSUPPORTED_IN_M1
                                    |
                                    v
                          +-----------------------+
                          | Transformation        |     Pattern-specific
                          | Generator (dispatch)  |     dbt SQL emission
                          +-----------------------+
                                    |
                                    v
                          +------------------+ ---> retry with error_hints
                          |  Validator       |      (DERIVED only, max 1 retry)
                          | (DuckDB sandbox) |
                          +------------------+
                                    |
                                    v
                          +------------------+
                          |  dbt-duckdb emit |
                          +------------------+
                                    |
                                    v
                            stg_*.sql + schema.yml
```

The whole pipeline is a [LangGraph](https://langchain-ai.github.io/langgraph/) state machine compiled in `packages/agents/src/agents/graph.py`. Every cross-agent payload is a Pydantic v2 contract from `packages/schemas/`.

## Quick demo

After install (below), three artifacts tell the story:

1. **Open the eval report** — `benchmarks/adventureworks/out/eval_report.json` shows every per-target match level, the SQL the agent emitted, and the validator pass rate. The `rates.inclusive` / `rates.exclusive` blocks at the top hold the headline numbers.

2. **Open an emitted dbt model** — `benchmarks/adventureworks/out/dbt/models/staging/stg_dim_customer_from_person_person.sql`. Every column has a trailing `-- pattern=...; source(s)=...; llm_conf=...; pass_rate=...` comment. That comment is the auditability story: every line is traceable to which agent decided it and how confident it was.

3. **Run the offline smoke test** — `scripts/smoke_graph.py` exercises the entire pipeline (graph + retry + dbt emit + dbt build) with a `FakeLLM` and zero API spend. Useful for CI and for verifying the system end-to-end in under a minute:
    ```bash
    ./.venv/Scripts/python.exe scripts/smoke_graph.py
    ```

## Install

Python 3.11 + venv + pip (no `uv`, no Docker — designed to run on locked-down corporate Windows machines).

```bash
git clone https://github.com/mohammad-alshaer/integration-agent.git
cd integration-agent
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e . \
  -e packages/schemas -e packages/sqlserver -e packages/agents \
  -e packages/generators -e packages/validator -e packages/dbt_emit \
  -e packages/evals -e apps/worker
cp .env.example .env   # fill in GEMINI_API_KEY
```

The `.env.example` is committed; the real `.env` stays gitignored.

## Run

### Profile a database

```bash
./.venv/Scripts/python.exe -m worker profile \
  --db AdventureWorks2022 --role source --out ./tmp/profiles/aw2022.json
```

Connects via ODBC + Windows auth, introspects via `INFORMATION_SCHEMA` + `sys.extended_properties`, profiles column statistics + samples FK-closure to Parquet, optionally enriches with LLM-inferred semantic types.

### Map a target table

```bash
./.venv/Scripts/python.exe -m worker run \
  --source-profile ./tmp/profiles/aw2022.json \
  --target-profile ./tmp/profiles/awdw2022.json \
  --target-table dbo.DimCustomer \
  --sample-dir benchmarks/adventureworks/samples \
  --out ./tmp/profiles/mappings_dimcustomer.json
```

### Run the full eval against the AdventureWorks golden set

```bash
./.venv/Scripts/python.exe -m evals \
  --pair adventureworks --provider gemini --model gemini-2.5-flash \
  --source-profile tmp/profiles/aw2022_filtered.json \
  --target-profile tmp/profiles/awdw2022.json \
  --rebuild-index --rate-limit-delay 0.5
```

Produces `benchmarks/adventureworks/out/eval_report.json` with the inclusive/exclusive accuracy rates, per-pattern breakdown, and the actual generated SQL alongside the expected pattern.

## Stack

- **Python 3.11** — runtime; everything is `pyproject.toml`-installable in editable mode.
- **LangGraph** — multi-agent orchestration with a conditional retry edge from validator back to the generator.
- **Gemini 2.5 Flash** (`google-genai`) — default LLM, provider-swappable via the `LLMClient` Protocol.
- **DuckDB + `vss` HNSW** — unified store for vector embeddings (RAG retrieval), Parquet-backed validator sandbox, and dbt-duckdb runtime. Replaces the original Postgres + pgvector + Postgres-as-warehouse plan because the corporate machine blocks Docker.
- **dbt-duckdb** — emitted dbt project runs locally against the same DuckDB the validator used; dbt-sqlserver swap is M4+.
- **Pydantic v2** — every cross-agent contract is a typed Pydantic model in `packages/schemas/`; no ad-hoc dicts cross specialist boundaries.

## Repo layout

```
apps/worker/          typer CLI: profile + run + version
packages/
  schemas/            Pydantic v2 contracts (the bus between agents)
  sqlserver/          ODBC connect, introspect, profile_stats, FK-closure sampler, PII redaction
  agents/             LLMClient + GeminiProvider + SHA-256 cache; embedders; vector store;
                      schema_explorer + semantic_matcher + pattern_classifier; LangGraph assembly
  generators/         PatternGenerator Protocol + Rename/Concat/Derived implementations
  validator/          DuckDB sandbox + error_hints normalizer + ValidationRunner
  dbt_emit/           project.yml + profiles.yml + model.sql + schema.yml emission
  evals/              golden YAML loader + scorer (3 match levels) + runner + CLI
benchmarks/
  adventureworks/     expected_mappings.yaml + Parquet samples + eval_report.json output
scripts/              smoke_graph.py is the canonical offline reproducibility check
docs/adr/             0001-langgraph, 0002-duckdb-unified-store, 0003-duckdb-parquet-sandbox,
                      0004-prompt-hash-caching
```

## Tests

```bash
./.venv/Scripts/python.exe -m pytest packages/ -q
```

100 tests across the workspace. Live SQL Server tests (`packages/sqlserver/tests/test_introspect.py`) skip cleanly when the SQLDEV2025 instance isn't reachable, so a fresh clone runs green without the dev DB.

## Roadmap

- **M1** (shipped) — multi-agent core, DuckDB validator + retry loop, dbt-duckdb emission, golden-set scorer, AdventureWorks first accuracy number.
- **M2** — lift DERIVED accuracy: stronger classifier prompts (few-shot RENAME-vs-DERIVED), DuckDB-aware generator dialect, multi-source-table JOIN modeling for pro-rated columns (TaxAmt, Freight). Add commutative-arg sorting in `normalize_sql` for richer SQL_SEMANTIC matches. Optional `ClaudeProvider` for A/B against Gemini.
- **M3** — FastAPI service wrapping the graph; expose mapping-as-a-service.
- **M4** — Next.js + shadcn UI for human-in-the-loop review of low-confidence mappings; `dbt-sqlserver` runtime swap so emitted projects target real SQL Server warehouses.

## Tech debt + caveats

- The corporate Windows machine running this blocks Docker / WSL / unsigned executables and proxies HTTPS through a corporate CA. `truststore.inject_into_ssl()` is wired into every script + CLI to make the certifi bundle trust the corporate root. Some bash builtins (`cat`, `wc`, `grep`, `tail`) are shell-allowlisted out, so workarounds are baked into the dev workflow (see `CLAUDE.md`).
- Gemini Flash free tier is 20 requests/day. Real eval runs require a paid tier-1 upgrade (~$0.30 per full benchmark) or a `ClaudeProvider` swap (~$0.10/run on Haiku 4.5 with prompt caching).
- Multi-source-table DERIVED specs (e.g. `FactInternetSales.TaxAmt` pro-rated from header tax + line subtotal) currently fall to a `_unmodeled_multi_source.txt` sidecar rather than emitting broken JOIN SQL. M2 work.

## License

Personal portfolio project. Code is MIT-licensed; see [`LICENSE`](LICENSE) if added.
