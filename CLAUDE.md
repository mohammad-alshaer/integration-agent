# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** M1 W4-C complete (16 commits on `main`, 100 tests passing). W4-D next. The full pipeline — graph → retry-with-error-hints → dbt emission → `dbt build` with passing tests, plus the golden-set scorer — is verified end-to-end offline via `scripts/smoke_graph.py` and the evals tests.

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
9f447bb  M1 W4-C: evals package + golden set + scorer + runner              (100 tests)
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

Tags: `m0-complete` on `afb7c6d`.

---

## What's left — pick up here in the new context window

### W4-D: docs + tag  ⏭️ DO THIS NEXT

- Fix the dbt `accepted_values` deprecation: in `packages/dbt_emit/src/dbt_emit/schema_yml.py`, wrap test configs under `arguments:` instead of top-level. Small change; kills the current `MissingArgumentsPropertyInGenericTestDeprecation` warning.
- Refresh CLAUDE.md one more time with W4-C landed (this file's "What's left" shrinks).
- Tag: `git tag m1-code-complete -m "M1 code-complete; real-LLM accuracy number pending"`.

### W4-E: first accuracy number  ⏳ QUOTA-GATED

Run the real-LLM eval against Gemini 2.5 Flash once:
- **Option A (free):** wait ~24h for the 20-req/day reset. Then `python -m evals run --pair adventureworks --provider gemini --model gemini-2.5-flash`.
- **Option B (cheap):** add Google AI Studio billing for tier-1 rate limits (1000 RPM on Flash; a full M1 eval of ~40 mappings × 2 LLM calls each = ~80 calls, well under $0.30).
- **Option C (alt):** swap provider to Claude Haiku 4.5 — ~15-line `ClaudeProvider` class implementing `LLMClient`; higher rate limits; ~$0.10/run.

Produces `benchmarks/adventureworks/out/eval_report.json` with:
- overall `exact_match` + `pattern_match` + `sql_semantic_match` rates (inclusive + exclusive of `disputed`)
- per-pattern breakdown (RENAME / CONCAT / DERIVED)
- prompt-cache hit rate
- tokens + estimated $/mapping
- `unsupported_in_m1` gap count

Separately verify:
```bash
./.venv/Scripts/python.exe -m dbt.cli.main build --project-dir benchmarks/adventureworks/out/dbt --profiles-dir benchmarks/adventureworks/out/dbt
```
Then tag:
```bash
git tag m1-complete -m "M1 complete — first accuracy number on AdventureWorks"
```

**M1 target accuracy (revised for Flash):** 35-55% exact match on first hot-cache run. Lower is fine; the number exists to measure M2 improvement, not to impress.

---

## Known-to-carry-over gotchas for the next session

1. **W4-B left an open accepted_values deprecation warning.** dbt 1.11 wants test configs under `arguments:` instead of top-level. Still passes; fix in W4-D.
2. **`packages/dbt_emit/src/dbt_emit/schema_yml.py` uses `# noqa: PLC2701`** to import "private" helpers from `model.py` (the `_model_name`, `_snake`, etc. underscore-prefixed functions). Refactor target for M2: move those into `dbt_emit/_parsing.py`.
3. **`scripts/smoke_graph.py` subprocess-runs `dbt build`.** If that's flaky, check the sandbox DuckDB file — the Parquet temp dir must outlive the `dbt build` call (we keep it alive inside a single `try:` block, cleanup in `finally:`).
4. **W3 left an observation that Gemini's embedding free tier is also tight** (~100 req/min + 100-request aggregate bucket that fills fast). `GeminiEmbedder` has `inter_batch_delay_sec=1.0` to smooth this.
5. The filtered real-LLM run at end of W3 (`tmp/profiles/mappings_dimcustomer.json`) produced 0 specs because we blew the daily Gemini Flash quota during the run's matcher/classifier calls. That run's shape proved graceful degradation works (un-enriched targets kept `UNKNOWN`, classifier failures mapped to `UNSUPPORTED_IN_M1`). Nothing broken; just waiting on quota for a clean rerun.

---

## When in doubt

1. Re-read the plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md`.
2. Check `MEMORY.md` for project/feedback notes.
3. For DataOps concept questions or Claude-specific how-tos, ask Mohammad — he's a new-grad, so explain foundational concepts (eval, RAG, dbt, embeddings, LangGraph state machines, etc.) with a concrete example tied to the current task. Don't just name-drop.
4. Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision.
