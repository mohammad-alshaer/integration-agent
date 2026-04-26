# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** **M1 complete** (tag `m1-complete`). Real-LLM accuracy number landed against Gemini 2.5 Flash (paid tier-1) on AdventureWorks: **65.8% inclusive / 83.3% exclusive** exact match, **72.6% validator pass rate**, **9/10 dbt models build clean**. 24+ commits on `main`, 104 tests passing, public repo at https://github.com/mohammad-alshaer/integration-agent. Three eval re-runs converged on the same accuracy number even after prompt + dialect-translator fixes — DERIVED 0/8 is the M2 target. Total session LLM spend: ~$0.32 of the $3 cap (most via prompt-hash cache).

**Canonical plan:** `C:\Users\mfalshaer\.claude\plans\i-want-to-do-jiggly-yeti.md` — read this before any non-trivial work. Always edit the plan incrementally when scope shifts; don't drift silently.

**Session memory:** `C:\Users\mfalshaer\.claude\projects\C--Users-mfalshaer-Desktop-PythonProjects-Integration-Agent\memory\` — read `MEMORY.md` for the index of user/feedback/project/reference notes.

---

## Corporate environment — read this FIRST

Mohammad's Dar-managed Windows 11 PC has hard policies. Ignoring them will cost hours.

| Blocked | Pivot |
|---|---|
| `uv` binary (installs to `.local\bin\`, not whitelisted) | Python's built-in `venv` + `pip`. Already set up at `.venv/`. |
| Docker Desktop / WSL / Podman | **DuckDB + `vss` extension** as unified metadata + vector store (supersedes Postgres+pgvector from the original plan). See ADR 0002. |
| pre-commit hook `.exe` wrappers (unsigned) | Run `ruff` manually from `.venv`. pre-commit will run in CI when a GitHub remote is added (M3+). |
| PowerShell (corporate restrictions on user-installed exes) | Use Git Bash; invoke `cmd //c "..."` when cmd-specific semantics needed. |
| Python default TLS (certifi bundle doesn't trust corporate CA) | **`truststore.inject_into_ssl()` at top of any script making HTTPS calls**, before any HTTPS client is constructed. Already wired into every script + `apps/worker/src/worker/cli.py`. |
| Gemini 2.5 Pro free tier (quota = 0 on this account) | Use `gemini-2.5-flash`. `.env.example` defaults to Flash. |
| **Gemini 2.5 Flash free tier = 20 requests per DAY** (hard cap — not per-minute) | Prompt-hash cache is the #1 defense — repeated runs burn ~0 quota on unchanged prompts. For full-scale eval runs: (a) wait for daily reset, (b) add Google AI Studio billing (~$0.30/full eval on Flash tier-1 at 1000 RPM), or (c) swap provider via `LLMClient` (a ~15-line `ClaudeProvider` would cost ~$0.10/run on Haiku 4.5). |
| **Gemini embedding free tier ~100 req/min** (not obvious from docs) | `GeminiEmbedder` has `inter_batch_delay_sec=1.0` by default + exponential retry up to 32s. |
| Voyage embeddings without a payment method (hard cap: 3 RPM / 10K TPM) | **Default embedder is Gemini, not Voyage.** Set `EMBEDDING_PROVIDER=voyage` only if a payment method is on file. |

**Bash sandbox quirks** (separate from AppLocker — it's the Claude tool shell's allowlist): `cat`, `wc`, `head`, `grep`, `tail`, `mkdir` are blocked. Workarounds:
- `git commit -m "..." -m "..."` multi-flag instead of HEREDOCs.
- Use the Write tool for file content, never `echo >` or `cat <<EOF`.
- Skip pipes to `head`/`tail`/`grep`; run the command raw.
- Use Python for `mkdir` (or Write tool implicit parent creation).

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

## Repo layout (end of W4-C)

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
./.venv/Scripts/python.exe -m pytest packages/ -v    # 100 tests at end of W4-C

# Smoke tests (all green; smoke_graph.py in particular is the offline DoD)
./.venv/Scripts/python.exe scripts/check_sqlserver.py
./.venv/Scripts/python.exe scripts/verify_adventureworks.py
./.venv/Scripts/python.exe scripts/check_duckdb.py
./.venv/Scripts/python.exe scripts/smoke_graph.py     # FakeLLM e2e: graph + retry + dbt build
./.venv/Scripts/python.exe scripts/hello_gemini.py    # 1 LLM call (watch quota)
./.venv/Scripts/python.exe scripts/smoke_embeddings.py # Gemini embedding quota

# Profile a database -> SchemaProfile JSON
./.venv/Scripts/python.exe -m worker profile \
  --db AdventureWorks2022 --role source --out ./tmp/profiles/aw2022.json \
  [--no-enrich] [--no-include-samples] [--rate-limit-delay 6.5]

# Run the mapping graph (real LLM — watch the 20-req/day Gemini Flash cap)
./.venv/Scripts/python.exe -m worker run \
  --source-profile ./tmp/profiles/aw2022.json \
  --target-profile ./tmp/profiles/awdw2022.json \
  --target-table dbo.DimCustomer \
  --sample-dir benchmarks/adventureworks/samples \
  --rebuild-index --rate-limit-delay 6.5 \
  --out ./tmp/profiles/mappings_dimcustomer.json

# dbt build verification (W4-B) — run against the emitted project
./.venv/Scripts/python.exe -m dbt.cli.main build \
  --project-dir benchmarks/adventureworks/out/dbt \
  --profiles-dir benchmarks/adventureworks/out/dbt \
  --target dev

# Eval harness — produces the accuracy-number JSON report (quota-gated for real LLM; use --provider fake offline)
./.venv/Scripts/python.exe -m evals run \
  --pair adventureworks --provider gemini --model gemini-2.5-flash
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
- Milestone commits = multiple-letter sub-milestones (e.g. `M1 W4-A`). Each sub-milestone is a single commit. Commit messages use multiple `-m` flags (Bash sandbox blocks HEREDOC-with-cat).
- Every commit ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Milestones tagged: `m0-complete`, planned `m1-code-complete` (end of W4-D) and `m1-complete` (after W4-E real-LLM accuracy number lands).
- Branch: `main` (renamed locally from `master`; no global git config changes).
- No pushes yet — no remote configured.

**Code style:**
- ruff enforces: line-length 100, select=`["E","F","I","W","B","UP","SIM"]`, ignore=`["E501","B008"]` (B008 ignored — typer's `typer.Option(...)` defaults are safe).
- Default to no comments. Write `# why` only when the reason is non-obvious.
- Never write multi-paragraph docstrings. One short line per function.
- Python 3.11 idioms: `from __future__ import annotations`, `|` unions, `list[T]`/`dict[K,V]` generics, `StrEnum`.

---

## Current status (commit log, newest first)

```
<pending> Refresh CLAUDE.md for M1-complete state                            (104 tests)
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

Tags: `m0-complete` on `afb7c6d`, `m1-code-complete` on `66db0a1`, `m1-complete` on `894ac59` (latest).
Public repo: https://github.com/mohammad-alshaer/integration-agent — first push landed mid-session.

---

## What's left — M2 entry-points

M1 is shipped + tagged + pushed. M2 starts here. Ordered by impact-to-effort:

### M2.1 — Lift DERIVED accuracy (highest ROI)

DERIVED is 0/8 exact in the M1 number. Three failure clusters from run #3 diagnosis:
- **2 stylistic alternatives** (`ExtendedAmount`, `SalesAmount`): classifier picks the persisted-computed source (`LineTotal`) which is semantically equivalent to the golden's primitive arithmetic. Either re-author the golden to accept this style, or add anti-stylistic few-shot to override.
- **1 genuinely wrong** (`DiscountAmount`): classifier picks `UnitPriceDiscount` alone (a percentage) instead of the arithmetic `UnitPrice * UnitPriceDiscount * OrderQty`. Sharper few-shot or a column-name heuristic.
- **4 UNSUPPORTED_IN_M1** (`TaxAmt`, `Freight`, `BirthDate`, `YearlyIncome`, `EmailAddress`, `DateFirstPurchase`): genuinely beyond M1 scope (multi-table allocations, XML shredding, aggregations, cross-table lookups). Each is a new pattern + generator.

### M2.2 — Multi-source-table DERIVED + JOIN modeling

The `_unmodeled_multi_source.txt` sidecar pattern in `packages/dbt_emit/src/dbt_emit/model.py` punts on multi-source specs. Extending it to emit JOIN-aware dbt models unlocks `FactInternetSales.TaxAmt`/`Freight` (and probably half a dozen more).

### M2.3 — DuckDB-executed SQL equivalence (4th match level)

Currently `SQL_SEMANTIC` only checks "does the normalized SQL contain every expected source column name?" — a token-level proxy. Real semantic equivalence: run both the expected and actual SQL against the sandbox and compare result sets. Bigger lift; truer signal.

### M2.4 — `ClaudeProvider`

~15-line `LLMClient` impl backed by `anthropic` SDK with prompt caching. Lets us A/B Flash vs Haiku 4.5 vs Sonnet 4.6 on the same golden set without changing any other code. Useful both for cost-shopping and as portfolio evidence of provider-swappable design.

### M2.5 — Commutative-arg sorting in `normalize_sql`

Tiny lift, modest scope (CONCAT_WS isn't commutative; benefits mostly arithmetic + COALESCE).

### M2.6 — `pipeline_dollars_total` field on EvalReport

Telemetry now reports tokens; per-provider price tables would convert that to dollars. Useful for M2 cost-comparison runs.

---

## Known-to-carry-over gotchas for the next session

1. **`scripts/smoke_graph.py` subprocess-runs `dbt build`.** If that's flaky, check the sandbox DuckDB file — the Parquet temp dir must outlive the `dbt build` call (we keep it alive inside a single `try:` block, cleanup in `finally:`).
2. **W3 left an observation that Gemini's embedding free tier is also tight** (~100 req/min + 100-request aggregate bucket that fills fast). `GeminiEmbedder` has `inter_batch_delay_sec=1.0` to smooth this.
3. **W4-E sample-dir** (`benchmarks/adventureworks/samples/`) has 19 Parquet files covering all 6 golden-source tables + FK parents. `Person.Address` and `HumanResources.Employee` failed sampling on ODBC type `-151` (geography/hierarchyid). Person.Address isn't on the golden path (non-blocker); `HumanResources.Employee` causes 1/10 dbt build error for the model the LLM emitted referencing it. Workaround for either: `CAST(... AS varchar)` in the SELECT inside `packages/sqlserver/src/sqlserver/sample.py` for unsupported ODBC types.
4. **`mean_llm_confidence=1.0`** in the eval report shows the model is overconfident — never says "I'm unsure" even when it's wrong (run #3 had several mismatches all at confidence=1.0). Calibration is M2-territory; needs prompt-engineered uncertainty.
5. **`tokens_in_total=0` + `prompt_cache_hit_rate=0%` per-spec** in the run #3 report is correct (run #3 was 100% cache hit) but misleading at first glance. The pipeline-level fields (`pipeline_total_llm_calls`, `pipeline_total_tokens_in/out`, `pipeline_cache_hit_rate`) tell the honest story; the per-spec fields only fire on cold runs.

---

## When in doubt

1. Re-read the plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md`.
2. Check `MEMORY.md` for project/feedback notes.
3. For DataOps concept questions or Claude-specific how-tos, ask Mohammad — he's a new-grad, so explain foundational concepts (eval, RAG, dbt, embeddings, LangGraph state machines, etc.) with a concrete example tied to the current task. Don't just name-drop.
4. Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision.
