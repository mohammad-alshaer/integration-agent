# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** **M2.2 complete** (tag `m2.2-complete`). Real-LLM accuracy on AdventureWorks (Gemini 2.5 Flash, paid tier-1): **73.7% inclusive / 90.0% exclusive** exact match (was 71.1% / 90.0% at M2.1.x; +2.6pp inclusive). RENAME 28/30 EXACT (was 26/30 — Phase A enrichment unlocked SalesAmount → RENAME[LineTotal] and ListPrice → RENAME[Production.Product.ListPrice]); DERIVED 0/8 EXACT (was 1/8 — ExtendedAmount regressed because the model now picks `Purchasing.PurchaseOrderDetail.LineTotal` over `Sales.SalesOrderDetail.LineTotal`; both have identical formula text). **Multi-source JOIN infrastructure landed** (validator FK-aware FROM clause synthesis + DerivedGenerator multi-source-mode + dbt_emit `intermediate/int_*.sql` model emission) but is unexercised by the AdventureWorks goldens this milestone — the classifier still picks single-table RENAME for TaxAmt/Freight/etc. **9/10 dbt models build clean** (HumanResources.Employee ODBC type -151 still the known fail). 30+ commits on `main`, 114 tests passing, public repo at https://github.com/mohammad-alshaer/integration-agent. Total M2.2 LLM spend: ~4 cents at Flash tier-1 (3 eval re-runs + target enrichment LLM pass).

**Baselines preserved on disk:** `benchmarks/adventureworks/out/eval_report.m1-baseline.json`, `eval_report.m2-1-baseline.json`, `eval_report.m2-2-final.json` (all gitignored but kept). Diff against `eval_report.json` to measure any future change.

**M2.3+ starts here:** Read the "What's left — M2 entry-points" section at the bottom. The most surprising M2.2 finding: **the classifier is the bottleneck for unlocking the multi-source JOIN infrastructure.** Even with rich descriptions and a working JOIN-aware validator, the classifier picks single-table RENAME for TaxAmt/Freight rather than multi-source DERIVED. The retrieval-side improvement of M2.2-A unlocked SalesAmount but didn't reach TaxAmt/Freight because their target descriptions don't surface multi-table candidates.

**Canonical M2.1+M2.1.x+M2.2 plan (historical reference):** `C:\Users\mfalshaer\.claude\plans\continue-with-m2-1-from-lexical-barto.md` — final state describes the M2.2 scope, predicted vs actual outcomes, and stop/cut decisions. Write a new plan file for M2.3 work.

**Canonical M1 plan (historical reference):** `C:\Users\mfalshaer\.claude\plans\i-want-to-do-jiggly-yeti.md` — describes the M1 scope; useful context but M1 is shipped. Write a new plan file for M2 work; don't edit the M1 one.

**Session memory:** `C:\Users\mfalshaer\.claude\projects\C--Users-mfalshaer-Desktop-PythonProjects-Integration-Agent\memory\` — read `MEMORY.md` for the index of user/feedback/project/reference notes.

---

## Corporate environment — read this FIRST

Mohammad's Dar-managed Windows 11 PC has hard policies. Ignoring them will cost hours.

| Blocked | Pivot |
|---|---|
| `uv` binary (installs to `.local\bin\`, not whitelisted) | Python's built-in `venv` + `pip`. Already set up at `.venv/`. |
| Docker Desktop / WSL / Podman | **DuckDB + `vss` extension** as unified metadata + vector store (supersedes Postgres+pgvector from the original plan). See ADR 0002. |
| pre-commit hook `.exe` wrappers (unsigned) | Run `ruff` manually from `.venv`. pre-commit will run in CI when a GitHub remote is added (M3+). |
| PowerShell (corporate restrictions + Kaspersky blocks on user-installed exes) | Order of preference: **Bash tool (Git Bash) > `cmd //c "..."` from Bash > PowerShell as last resort.** Mohammad reinforced this 2026-04-26: PS is most likely to be blocked by Kaspersky's process heuristics. |
| Python default TLS (certifi bundle doesn't trust corporate CA) | **`truststore.inject_into_ssl()` at top of any script making HTTPS calls**, before any HTTPS client is constructed. Already wired into every script + `apps/worker/src/worker/cli.py`. |
| Gemini 2.5 Pro free tier (quota = 0 on this account) | Use `gemini-2.5-flash`. `.env.example` defaults to Flash. |
| **Gemini 2.5 Flash free tier = 20 requests per DAY** (hard cap — not per-minute) | Prompt-hash cache is the #1 defense — repeated runs burn ~0 quota on unchanged prompts. For full-scale eval runs: (a) wait for daily reset, (b) add Google AI Studio billing (~$0.30/full eval on Flash tier-1 at 1000 RPM), or (c) swap provider via `LLMClient` (a ~15-line `ClaudeProvider` would cost ~$0.10/run on Haiku 4.5). |
| **Gemini embedding free tier ~100 req/min** (not obvious from docs) | `GeminiEmbedder` has `inter_batch_delay_sec=1.0` by default + exponential retry up to 32s. |
| Voyage embeddings without a payment method (hard cap: 3 RPM / 10K TPM) | **Default embedder is Gemini, not Voyage.** Set `EMBEDDING_PROVIDER=voyage` only if a payment method is on file. |

**Bash sandbox quirks** (separate from AppLocker — it's the Claude tool shell's allowlist):
- Some core utils (`cat`, `wc`, `mkdir`) may be blocked depending on the harness version. As of 2026-04-26 `tail`, `head`, `grep` work in piped commands. If a util fails with "Permission denied", fall back to dedicated tools (Read/Write/Glob/Grep) or to `cmd //c "..."`.
- `git commit -m "..." -m "..."` multi-flag instead of HEREDOCs (HEREDOC-with-cat is unreliable).
- Use the Write tool for file content, never `echo >` or `cat <<EOF`.
- Use Python or the Write tool for `mkdir` (Write creates parents implicitly).
- The `Grep` tool is dramatically faster than shelling out to `rg`/`grep`; prefer it for searches.

**What works:** Python (whitelisted), `.venv/Scripts/*` binaries, SQL Server 2025 Developer Edition (instance `SQLDEV2025`) via ODBC Driver 18 with Windows auth, DuckDB in-process, Git, pip (recent pip auto-uses truststore), Voyage/Google embeddings via `truststore`.

---

## Stack

- **Python 3.11** + `.venv/` + pip (no uv)
- **LangGraph** (`>=0.2,<0.3`) for multi-agent orchestration; compiled graph in `packages/agents/src/agents/graph.py`
- **Gemini 2.5 Flash** via `google-genai` SDK — default LLM behind `LLMClient` protocol (`packages/agents/src/agents/llm.py`); provider-swappable
- **Gemini `gemini-embedding-001`** as default embedder (1024 dims via `output_dimensionality`); `VoyageEmbedder` with `voyage-3-large` as alternative. Both behind the `Embedder` protocol, share SHA-256 content cache under `.cache/embeddings/`.
- **DuckDB + `vss` HNSW** — unified metadata + vector + sandbox store
- **SQL Server 2025 Developer Edition** — source of truth (AdventureWorks 2022 restored: `AdventureWorks2022` + `AdventureWorksDW2022`)
- **dbt-duckdb** — emitted dbt project runs against the same Sandbox DuckDB file (M1-M3); `dbt-sqlserver` later in M4+
- **Langfuse** cloud free tier for LLM observability
- **FastAPI** (M3+), **Next.js 14** + shadcn/ui (M4+)
- **Pydantic v2** for every contract between specialists (`packages/schemas/`)

---

## Repo layout (M1-complete)

```
Integration-Agent/
├── .venv/                           gitignored; AppLocker-allowed Python binaries
├── .duckdb/                         gitignored; unified metadata + vector + sandbox files
├── .cache/{llm,embeddings}/         gitignored; SHA-256 prompt-hash caches
├── .env                             gitignored; GEMINI + LANGFUSE + VOYAGE keys
├── .env.example                     template (committed; no secrets)
├── pyproject.toml                   root; deps + ruff/mypy/pytest config
├── CLAUDE.md                        this file
│
├── scripts/
│   ├── check_sqlserver.py           SQL Server connectivity + DB list
│   ├── verify_adventureworks.py     row-count assertions vs MS published numbers
│   ├── check_duckdb.py              DuckDB + vss HNSW smoke test
│   ├── hello_gemini.py              Gemini + Langfuse structured-output smoke test
│   ├── smoke_embeddings.py          Voyage/Gemini + vector store smoke test on AW subset
│   └── smoke_graph.py               FakeLLM end-to-end: graph -> validator-triggered retry -> dbt emit -> dbt build. Zero network, zero quota. The canonical offline verification.
│
├── apps/
│   └── worker/                      typer CLI (integration-agent-worker)
│                                    subcommands: profile, run, version
│
├── packages/
│   ├── schemas/                     Pydantic contracts: profile, candidates, patterns,
│   │                                mapping, validation, trace. The contract between specialists.
│   ├── sqlserver/                   connect, introspect (INFORMATION_SCHEMA + sys.extended_properties),
│   │                                profile_stats, sample (FK-closure -> Parquet), redaction
│   ├── agents/                      LLMClient + GeminiProvider + SHA-256 cache; Embedder (Voyage + Gemini);
│   │                                vector_store (DuckDB+vss); schema_explorer; semantic_matcher;
│   │                                pattern_classifier; transformation_generator; graph (LangGraph assembly w/ validator + retry)
│   ├── generators/                  PatternGenerator Protocol + Rename/Concat/Derived. GenerationContext carries optional error_hints for DerivedGenerator retries.
│   ├── validator/                   Sandbox (DuckDB in-memory OR persistent) + error_hints normalizer + ValidationRunner. Fills MappingSpec.validation_pass_rate.
│   ├── dbt_emit/                    project.py + profiles.py + model.py + schema_yml.py + emitter.py. Emits a dbt-duckdb project from a MappingSpec list.
│   ├── evals/                       models.py + golden.py (YAML loader) + scorer.py (3 match levels, per-pattern, disputed filter) + runner.py + cli.py. Produces eval_report.json.
│   └── (M3+: add api/, etc.)
│
├── benchmarks/
│   └── adventureworks/
│       ├── samples/                 gitignored; Parquet samples from FK-closure sampler
│       ├── expected_mappings.yaml   hand-authored ground truth for DimCustomer, DimProduct, FactInternetSales (~40 entries, ~1/4 disputed)
│       └── out/                     gitignored; dbt project + eval report
│
├── docs/adr/                        0001-langgraph, 0002-duckdb-unified-store,
│                                    0003-duckdb-parquet-sandbox, 0004-prompt-hash-caching
│
├── tmp/                             gitignored; ad-hoc outputs
└── description.txt                  Mohammad's original project description
```

Every `packages/*/` has its own `pyproject.toml`. Install every workspace package editable after a fresh clone:

```bash
./.venv/Scripts/python.exe -m pip install -e . \
  -e packages/schemas -e packages/sqlserver -e packages/agents \
  -e packages/generators -e packages/validator -e packages/dbt_emit \
  -e packages/evals -e apps/worker
```

---

## Common commands

**ALWAYS invoke Python through the venv path**, not global. AppLocker allows `.venv/Scripts/python.exe` but the global Python doesn't have our packages.

```bash
# Lint + format + tests (run manually — pre-commit is dropped on this machine)
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format .
./.venv/Scripts/python.exe -m pytest packages/ -q    # 104 tests at M1-complete

# Smoke tests (all green; smoke_graph.py in particular is the offline DoD)
./.venv/Scripts/python.exe scripts/check_sqlserver.py
./.venv/Scripts/python.exe scripts/verify_adventureworks.py
./.venv/Scripts/python.exe scripts/check_duckdb.py
./.venv/Scripts/python.exe scripts/smoke_graph.py     # FakeLLM e2e: graph + retry + dbt build
./.venv/Scripts/python.exe scripts/hello_gemini.py    # 1 LLM call (Flash paid tier — cheap)
./.venv/Scripts/python.exe scripts/smoke_embeddings.py # Gemini embedding quota

# Profile a database -> SchemaProfile JSON
./.venv/Scripts/python.exe -m worker profile \
  --db AdventureWorks2022 --role source --out ./tmp/profiles/aw2022.json \
  [--no-enrich] [--no-include-samples] [--rate-limit-delay 6.5]

# Run the mapping graph for a single target table (real LLM — Flash paid tier-1 in use)
./.venv/Scripts/python.exe -m worker run \
  --source-profile ./tmp/profiles/aw2022_filtered.json \
  --target-profile ./tmp/profiles/awdw2022.json \
  --target-table dbo.DimCustomer \
  --sample-dir benchmarks/adventureworks/samples \
  --rebuild-index --rate-limit-delay 0.5 \
  --out ./tmp/profiles/mappings_dimcustomer.json

# dbt build against the emitted project (after a full eval run)
./.venv/Scripts/python.exe -m dbt.cli.main build \
  --project-dir benchmarks/adventureworks/out/dbt \
  --profiles-dir benchmarks/adventureworks/out/dbt \
  --target dev

# Eval harness — single command (no `run` subcommand). Produces eval_report.json.
# All cache hits = ~$0; cold cache = ~$0.30 on Flash paid tier-1.
./.venv/Scripts/python.exe -m evals \
  --pair adventureworks --provider gemini --model gemini-2.5-flash \
  --source-profile tmp/profiles/aw2022_filtered.json \
  --target-profile tmp/profiles/awdw2022.json \
  --rebuild-index --rate-limit-delay 0.5

# Re-emit + dbt build from a cached eval report (no LLM cost; reconstructs MappingSpecs from eval_report.json)
# See the inline pattern used at end-of-M1; consider promoting to a `scripts/dbt_build_from_report.py` if reused.
```

---

## Conventions

**Structure:**
- Contracts live in `packages/schemas/` — never let ad-hoc dicts leak between specialists. Pydantic v2 everywhere.
- LLM calls ALWAYS go through `LLMClient.structured()`. It enforces prompt-hash caching, provider swappability, retry-with-backoff on 429/5xx, and cost metadata attachment.
- **Two confidences — never merged:** `llm_confidence` (model self-report) and `validation_pass_rate` (measured in DuckDB sandbox by the validator). UI/logs show both.
- dbt output lives under `benchmarks/<pair>/out/dbt/`. Every generated `.sql` line carries a tail comment: `-- pattern=<p>; source(s)=<fqn,fqn>; llm_conf=<0-1>; pass_rate=<0-1>`.
- **Pattern scope discipline is visible in code:** `Pattern.UNSUPPORTED_IN_M1` is an explicit enum value the classifier emits for any non-M1 pattern. `transformation_generator.py` skips those with a log line; `dbt_emit.model.write_models` leaves multi-source-table specs in a `_unmodeled_multi_source.txt` sidecar rather than emitting broken SQL. Don't stub fake generators for SPLIT/CONSTANT/etc.
- **Validator -> generator retry loop:** only `DerivedGenerator` consumes `error_hints`. `GraphState.retry_count` + conditional edge `validator -> transformation_generator` (when any DERIVED spec failed AND retry_count < max_retries). Default `max_retries=1` (= initial + 1 retry). Rename/concat failures aren't retry-fixable; they stay in the report as passed=False.

**LLM / network code:**
- Any script that opens an HTTPS connection starts with:
  ```python
  import truststore
  truststore.inject_into_ssl()
  ```
  Before the imports that construct HTTPS clients. Subsequent imports get `# noqa: E402`.
- Don't read `.env` into the conversation; scripts load it via `python-dotenv`.
- Default to `gemini-2.5-flash`. Model name is read from `GEMINI_MODEL` env var — upgrade to Pro is a billing decision, not a code change.
- Default embedder is `GeminiEmbedder` (`EMBEDDING_PROVIDER=gemini`). Voyage is alternative.
- **Hallucination guards:** Semantic Matcher + Pattern Classifier post-filter LLM output against the retrieved candidate set. Any `source_fqn` not in the retrieved top-K gets dropped with a log warning.

**Testing + offline verification:**
- **`FakeLLM` pattern:** unit tests + `scripts/smoke_graph.py` use classes that implement `LLMClient` with scripted responses. Keeps test runs fast, provider-agnostic, and independent of API quotas / provider uptime. `smoke_graph.py::FakeLLM._derived` even uses "PREVIOUS ATTEMPT FAILED" as a signal to return corrected SQL, exercising the retry path deterministically.
- **Live integration tests** (e.g. `packages/sqlserver/tests/test_introspect.py`) use `pytest.mark.skipif(not _server_reachable(), ...)` so fresh clones without SQLDEV2025 don't fail.
- **dbt build verification** runs inside `scripts/smoke_graph.py`: it emits the project, then subprocess-runs `python -m dbt.cli.main build` against it. Exit code 0 + 3 dbt tests passing (not_null, unique, accepted_values) was the W4-B DoD.
- Don't rely on real-LLM runs in pytest — prompt-hash cache makes them free on re-run but first-run quota burn is real.

**Git workflow:**
- Milestone commits = multiple-letter sub-milestones (e.g. `M2.1 ...`). Each sub-milestone is a single commit. Commit messages use multiple `-m` flags (Bash sandbox blocks HEREDOC-with-cat).
- Every commit ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Milestones tagged: `m0-complete` (`afb7c6d`), `m1-code-complete` (`66db0a1`), `m1-complete` (`894ac59`).
- Branch: `main`. **Remote configured: `origin → https://github.com/mohammad-alshaer/integration-agent` (public).** Push with `git push origin main && git push origin --tags`.
- When self-referencing a hash in a doc that hasn't been committed yet, write `<pending>` and fill in via a small follow-up "Refresh" commit (this is a known cosmetic drift; harmless).

**Code style:**
- ruff enforces: line-length 100, select=`["E","F","I","W","B","UP","SIM"]`, ignore=`["E501","B008"]` (B008 ignored — typer's `typer.Option(...)` defaults are safe).
- Default to no comments. Write `# why` only when the reason is non-obvious.
- Never write multi-paragraph docstrings. One short line per function.
- Python 3.11 idioms: `from __future__ import annotations`, `|` unions, `list[T]`/`dict[K,V]` generics, `StrEnum`.

---

## Current status (commit log, newest first)

```
1fab32e  Refresh CLAUDE.md for M2.2-complete state                         (114 tests)
fc83c60  M2.2: Lift accuracy 71.1% -> 73.7% via target enrichment + multi-source JOIN infrastructure (114 tests)
f31f7b3  Fill in M2.1.x commit hash in CLAUDE.md log                          (108 tests)
6449d6f  M2.1.x: revert classifier disambiguation bullet + document retrieval blockers (108 tests)
0887f75  Fill in m2.1-complete tag hash + CLAUDE.md refresh hash             (108 tests)
492afa7  Refresh CLAUDE.md for M2.1-complete state                         (108 tests)
4346c93  M2.1: Lift accuracy 65.8% -> 71.1% via prompt + retrieval + multi-acceptable goldens (108 tests)
0c7c498  Polish CLAUDE.md hand-off for fresh M2 session                     (104 tests)
45c9fb8  Refresh CLAUDE.md for M1-complete state                            (104 tests)
894ac59  Translate SQL Server types to DuckDB equivalents in Rename CAST    (104 tests)
96e8c1c  Lift accuracy: DuckDB dialect hint in DERIVED + classifier few-shot (103 tests)
4b4b402  Wire Gemini usage_metadata into LLMClient + EvalReport telemetry   (103 tests)
6b4d4b9  Rewrite README for M1-complete state
57573f5  Rename schema.yml 'tests:' key to 'data_tests:' for dbt 1.10+ compat (100 tests)
706dc8c  Refresh CLAUDE.md for end-of-W4-D + M2-prep state                  (100 tests)
1a24ebe  Refactor: extract dbt_emit parsing helpers into _parsing.py        (100 tests)
66db0a1  M1 W4-D: dbt accepted_values deprecation fix + CLAUDE.md refresh   (100 tests)
c341760  M1 W4-C: evals package + golden set + scorer + runner              (100 tests)
43b4360  M1 W4-B: dbt_emit package + dbt-duckdb build verification          (79 tests)
93379ff  M1 W4-A: DuckDB sandbox validator + retry-with-error-hints loop    (70 tests)
bb09763  Refresh CLAUDE.md for end-of-W3 state
4832a5d  M1 W3-D: LangGraph graph + worker run subcommand + smoke_graph e2e (47 tests)
d266fed  M1 W3-C: packages/generators + transformation_generator dispatcher (47 tests)
81dda7b  M1 W3-B: Semantic Matcher + Pattern Classifier                     (35 tests)
b2e5861  M1 W3-A: Voyage embeddings + DuckDB+vss vector store               (25 tests)
2eeee87  Add tmp/ to .gitignore
d698c40  M1 W2: Schema Explorer agent + apps/worker CLI + tests
0ceb1b1  M1 W2: packages/sqlserver — introspect + profile stats + sampling + PII
ff1402e  Add CLAUDE.md for future Claude Code sessions
afb7c6d  M0 Day 4 verified: truststore for corp TLS proxy + Gemini Flash default
c86a309  M0 Day 5: schemas + agents LLMClient + 4 ADRs
df0a8ae  M0 Day 4 scaffolding: Gemini + Langfuse ready for API keys
2fb4ae6  M0 Day 3: DuckDB + vss as unified metadata + vector store
97c64ee  M0 Day 2: SQL Server + AdventureWorks verified from Python
2df890d  M0 Day 1: scaffold
```

Tags: `m0-complete` on `afb7c6d`, `m1-code-complete` on `66db0a1`, `m1-complete` on `894ac59`, `m2.1-complete` on `4346c93`, `m2.2-complete` on `fc83c60` (latest).
Public repo: https://github.com/mohammad-alshaer/integration-agent — first push landed mid-M1 session.

---

## What's left — M2 entry-points

M1 + M2.1 + M2.1.x + M2.2 are shipped + tagged + pushed. M2.3+ starts here. Ordered by impact-to-effort:

### M2.2.x — ExtendedAmount disambiguation (small, follow-up)

M2.2's Phase A enrichment unlocked SalesAmount but introduced a regression: `dbo.FactInternetSales.ExtendedAmount` now picks `Purchasing.PurchaseOrderDetail.LineTotal` instead of `Sales.SalesOrderDetail.LineTotal`. Both have identical formula text in the source profile (`OrderQty * UnitPrice`-style), so the embedder/rerank can't distinguish them by formula alone. The signal that should disambiguate them — "this target is from FactInternetSales, which is about internet SALES, prefer Sales.* sources over Purchasing.*" — isn't surfaced in the matcher prompt today.

**Approaches to evaluate (~30 min each):**
- Add target-table-context line to `_format_target` in `semantic_matcher.py` (e.g. "Target table: FactInternetSales — fact table for internet sales transactions")
- Extend Schema Explorer to also generate per-table descriptions, then surface in the matcher prompt
- Add an additional accepted_alternative to ExtendedAmount golden (semantically wrong — Purchasing isn't equivalent — so this is a no)

### M2.3 — Make the classifier emit multi-source DERIVED

M2.2 landed the multi-source JOIN infrastructure (validator, dbt_emit `intermediate/` models, generator multi-source mode) but the classifier still picks single-table RENAME for TaxAmt/Freight. The infra is dormant infrastructure ready to be exercised by future classifier improvements.

**Why M2.2's Phase B2 (TaxAmt few-shot) failed:** Same failure mode as M2.1.x DiscountAmount — when the canonical sources aren't all in the top-K candidates, the model falls back to `unsupported_in_m1` instead of attempting. Fixes require:
- **Better cross-table retrieval** (target descriptions that reference allocation patterns, OR a JOIN-aware retrieval step that surfaces FK-linked candidates), AND
- **Classifier robustness** (handle "few-shot suggests N sources but candidates have M < N" gracefully — emit DERIVED with M sources rather than UNSUPPORTED).

This is genuinely complex and may need its own multi-step plan.

### M2.4 — DuckDB-executed SQL equivalence (4th match level)

Currently `SQL_SEMANTIC` only checks "does the normalized SQL contain every expected source column name?" — a token-level proxy. Real semantic equivalence: run both the expected and actual SQL against the sandbox and compare result sets. Bigger lift; truer signal.

### M2.5 — `ClaudeProvider`

~15-line `LLMClient` impl backed by `anthropic` SDK with prompt caching. Lets us A/B Flash vs Haiku 4.5 vs Sonnet 4.6 on the same golden set without changing any other code. Useful both for cost-shopping and as portfolio evidence of provider-swappable design.

### M2.6 — Commutative-arg sorting in `normalize_sql`

Tiny lift, modest scope (CONCAT_WS isn't commutative; benefits mostly arithmetic + COALESCE).

### M2.7 — `pipeline_dollars_total` field on EvalReport

Telemetry now reports tokens; per-provider price tables would convert that to dollars. Useful for M2 cost-comparison runs.

---

## Known-to-carry-over gotchas for the next session

1. **`scripts/smoke_graph.py` subprocess-runs `dbt build`.** If that's flaky, check the sandbox DuckDB file — the Parquet temp dir must outlive the `dbt build` call (we keep it alive inside a single `try:` block, cleanup in `finally:`).
2. **W3 left an observation that Gemini's embedding free tier is also tight** (~100 req/min + 100-request aggregate bucket that fills fast). `GeminiEmbedder` has `inter_batch_delay_sec=1.0` to smooth this.
3. **W4-E sample-dir** (`benchmarks/adventureworks/samples/`) has 19 Parquet files covering all 6 golden-source tables + FK parents. `Person.Address` and `HumanResources.Employee` failed sampling on ODBC type `-151` (geography/hierarchyid). Person.Address isn't on the golden path (non-blocker); `HumanResources.Employee` causes 1/10 dbt build error for the model the LLM emitted referencing it. Workaround for either: `CAST(... AS varchar)` in the SELECT inside `packages/sqlserver/src/sqlserver/sample.py` for unsupported ODBC types.
4. **`mean_llm_confidence=1.0`** in the eval report shows the model is overconfident — never says "I'm unsure" even when it's wrong (run #3 had several mismatches all at confidence=1.0). Calibration is M2-territory; needs prompt-engineered uncertainty.
5. **`tokens_in_total=0` + `prompt_cache_hit_rate=0%` per-spec** in the run #3 report is correct (run #3 was 100% cache hit) but misleading at first glance. The pipeline-level fields (`pipeline_total_llm_calls`, `pipeline_total_tokens_in/out`, `pipeline_cache_hit_rate`) tell the honest story; the per-spec fields only fire on cold runs.

6. **`tmp/profiles/aw2022_filtered.json` was enriched in place during M2.1** with `computed_definition` for the 10 computed columns in AdventureWorks2022 (notably `Sales.SalesOrderDetail.LineTotal` and `Sales.SalesOrderHeader.TotalDue`). The one-off enrichment script lives at `tmp/enrich_computed.py` (gitignored). If you re-profile from scratch via `python -m worker profile`, the new field is populated automatically by `introspect.py`. Backward-compat: `computed_definition` is `Optional[str]`, so old profile JSONs load fine.

7. **The classifier prompt is ~5 LoC longer than M1** (M2.1 added 2 few-shot examples for ExtendedAmount + SalesAmount; M2.1.x removed the 4-LoC amount-vs-percentage disambiguation bullet because it was over-prescriptive). Watch for prompt-bloat regressions when adding more disambiguation rules — the M2.1.x DiscountAmount investigation showed that prescriptive bullets without reachable canonical sources push the model into `unsupported_in_m1`.

8. **Target-side description enrichment landed in M2.2.** Schema Explorer now generates `ms_description` for description-bare columns (Phase A). The current `tmp/profiles/awdw2022.json` has all 91 target columns enriched in place via `tmp/enrich_target_descriptions.py` (gitignored). If you re-derive the AWDW profile from scratch via `worker profile --enrich`, the new field is populated automatically. **The descriptions are LLM-generated, not from sys.extended_properties** — they're labeled "generated_description" in the enrichment output and folded into ms_description only when missing.

9. **Multi-source JOIN infrastructure (M2.2 Phase B1) is live but unexercised.** `validator.runner._resolve_from` handles 2-table specs by FK lookup via `ColumnProfile.fk_ref`; `dbt_emit.write_models` emits `intermediate/int_*.sql` JOIN models when `source_profile` is supplied; `DerivedGenerator` understands multi-source-table mode (TABLE.column prefixes, JOIN HINT in user prompt). But the classifier still picks single-table RENAME for TaxAmt/Freight, so this code path runs only on synthetic test fixtures, not real eval specs. Future M2.3 work to make the classifier emit multi-source DERIVED will exercise this for free.

10. **Known M2.2 regression — ExtendedAmount.** Was EXACT in M2.1 (via the RENAME[Sales.SalesOrderDetail.LineTotal] alternative); is MISMATCH in M2.2 because the model now picks `Purchasing.PurchaseOrderDetail.LineTotal` (same formula text, wrong domain). Documented as M2.2.x. Quick fixes to try: target-table-context line in `_format_target` of `semantic_matcher.py`; or per-table description enrichment.

---

## When in doubt

1. **For M2.2.x or M2.3+ work:** start with the "What's left — M2 entry-points" section above. Compare any change against the M2.2 numbers in `benchmarks/adventureworks/out/eval_report.json` (the live report) AND `eval_report.m2-2-final.json` (the M2.2 baseline) AND `eval_report.m1-baseline.json` (the M1 floor). All are gitignored but kept on disk.
2. **For project history:** the M1 plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md` and the M2.1+M2.1.x+M2.2 evolved plan at `~/.claude/plans/continue-with-m2-1-from-lexical-barto.md` are reference-only.
3. **Memory:** check `MEMORY.md` for project/feedback notes about Mohammad's preferences and corporate environment specifics.
4. **For DataOps / Claude-specific concept questions**, explain foundational concepts (eval, RAG, dbt, embeddings, LangGraph state machines, etc.) with a concrete example tied to the current task. Mohammad is a new-grad — don't just name-drop.
5. **Cost discipline:** Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision. Gemini Flash paid tier-1 is already configured (~$0.30/full eval; cache makes re-runs nearly free).
6. **Before any GitHub push:** verify no secrets in the diff. The repo is **public**; anything pushed is permanently visible.
