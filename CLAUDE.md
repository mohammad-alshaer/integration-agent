# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** **M4 COMPLETE** (umbrella tag `m4-complete` on commit `998b52f`). The full M4 series shipped: M4.1 → M4.2 → M4.3. Browser-facing UI for the M3 service at `apps/web/`: Next.js 16 + React 19 + Tailwind v4 + TypeScript, `DESIGN.md`-driven Composio aesthetic (Void Black canvas, Composio Cobalt + Electric Cyan accents, Geist Sans + JetBrains Mono via `next/font/google`, brutalist 4px-offset shadow utility, 0.87 heading line-heights). 6 user routes: `/` (landing with hero gradient + nav cards), `/eval` (server-component table over `GET /eval`), `/eval/[run_id]` (rates matrix card + per-spec ScoreEntry table with disputed-row dimming), `/map` (client-component form with file upload + AbortController-cancel + cyan elapsed-timer for 10s–5min POST `/map` requests), `/health` (full HealthResponse surface + opt-in deep probe button), `not-found.tsx`. HealthPill in the Brand header polls `GET /health` every 30s. **CORS pre-wired**, no auth, no JS-side tests yet (M4.x). Verification: `npm run lint` clean, `npm run build` green, Python regression stays at **137 passed** (130 packages + 7 in `apps/api/tests/`).

**Prior milestone:** **M3 COMPLETE** — FastAPI service layer (commit `36a429f`). The mapping graph is reachable as an HTTP service: `GET /health [+?deep]`, `POST /map`, `GET /eval`, `GET /eval/{run_id}`. Sync handler in `asyncio.to_thread` under a global `asyncio.Lock`, 600s hard timeout, single target table per request, inline `SchemaProfile` Pydantic in the request body, glob-based eval lookup with a 60s TTL cache. ADR `docs/adr/0005-fastapi-service-layer.md` captures the decisions.

**Prior milestone:** **M2 COMPLETE** (umbrella tag `m2-complete` on commit `3ff37a7`). M1 → M2.1 → M2.1.x → M2.2 → M2.3 → M2.3.x → M2.4 → M2.5 → M2.6 → M2.7. Real-LLM accuracy on AdventureWorks (Gemini 2.5 Flash): **78.9% inclusive / 96.7% exclusive** exact match. RENAME 29/30 EXACT, DERIVED 1/8 EXACT. **9/10 dbt models build clean**. Total M2 LLM spend: ~5 cents at Flash tier-1.

**Baselines preserved on disk:** `benchmarks/adventureworks/out/eval_report.m1-baseline.json`, `eval_report.m2-1-baseline.json`, `eval_report.m2-2-final.json`, `eval_report.m2-3-final.json`, `eval_report.m2-3-x-final.json`, `eval_report.m2-complete.json` (all gitignored but kept). Diff against `eval_report.json` to measure any future change.

**What's next:** the portfolio shape is now complete end-to-end (CLI → API → UI). The remaining workstreams are parallel/optional and listed at impact-to-effort below. Top of mind: **M3.1 = SSE streaming progress for `POST /map`** (would replace the spinner-only UX with per-node graph events) and **M5 = deploy** (publish the demo somewhere reachable, e.g. fly.io for the API + Vercel for the web). Eval-side lifts (JOIN-aware retrieval for TaxAmt/Freight, real Claude A/B run) remain genuinely parallel.

**Canonical M4 plan (historical reference):** `C:\Users\mfalshaer\.claude\plans\lets-start-working-on-refactored-prism.md` — describes the M4.1 scaffold + DESIGN.md token wiring + sub-milestone breakdown. The plan was scoped to M4.1 only; M4.2 and M4.3 were executed without separate plan files. Useful context but M4 is shipped.

**Canonical M3 plan (overwritten — see M4 plan).** The M3 plan was overwritten when M4 began. M3 history lives in commit messages and `docs/adr/0005-fastapi-service-layer.md`.

**Canonical evolved plan (historical reference):** `C:\Users\mfalshaer\.claude\plans\continue-with-m2-1-from-lexical-barto.md` — describes the full M2 evolution from M2.1 through the final 5-sub-milestone finish.

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
├── DESIGN.md                        Composio-inspired design system (M4 UI reference; dark theme, cyan/cobalt accents, JetBrains Mono + abcDiatype). Generated via `npx getdesign@latest add composio`.
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
│   ├── worker/                      typer CLI (integration-agent-worker)
│   │                                subcommands: profile, run, version
│   ├── api/                         FastAPI service (integration-agent-api)
│   │                                endpoints: GET /health [+?deep], POST /map, GET /eval[/{run_id}]
│   └── web/                         Next.js 16 + Tailwind v4 + React 19 frontend (M4.1: /, /eval, /eval/[run_id])
│                                    Server Components + server-side fetch against M3 API. NEXT_PUBLIC_API_BASE_URL.
│
├── packages/
│   ├── schemas/                     Pydantic contracts: profile, candidates, patterns,
│   │                                mapping, validation, trace, api. The contract between specialists.
│   ├── sqlserver/                   connect, introspect (INFORMATION_SCHEMA + sys.extended_properties),
│   │                                profile_stats, sample (FK-closure -> Parquet), redaction
│   ├── agents/                      LLMClient + GeminiProvider + SHA-256 cache; Embedder (Voyage + Gemini);
│   │                                vector_store (DuckDB+vss); schema_explorer; semantic_matcher;
│   │                                pattern_classifier; transformation_generator; graph (LangGraph assembly w/ validator + retry)
│   ├── generators/                  PatternGenerator Protocol + Rename/Concat/Derived. GenerationContext carries optional error_hints for DerivedGenerator retries.
│   ├── validator/                   Sandbox (DuckDB in-memory OR persistent) + error_hints normalizer + ValidationRunner. Fills MappingSpec.validation_pass_rate.
│   ├── dbt_emit/                    project.py + profiles.py + model.py + schema_yml.py + emitter.py. Emits a dbt-duckdb project from a MappingSpec list.
│   └── evals/                       models.py + golden.py (YAML loader) + scorer.py (3 match levels, per-pattern, disputed filter) + runner.py + cli.py. Produces eval_report.json.
│
├── benchmarks/
│   └── adventureworks/
│       ├── samples/                 gitignored; Parquet samples from FK-closure sampler
│       ├── expected_mappings.yaml   hand-authored ground truth for DimCustomer, DimProduct, FactInternetSales (~40 entries, ~1/4 disputed)
│       └── out/                     gitignored; dbt project + eval report
│
├── docs/adr/                        0001-langgraph, 0002-duckdb-unified-store,
│                                    0003-duckdb-parquet-sandbox, 0004-prompt-hash-caching,
│                                    0005-fastapi-service-layer
│
├── tmp/                             gitignored; ad-hoc outputs
└── description.txt                  Mohammad's original project description
```

Every `packages/*/` has its own `pyproject.toml`. Install every workspace package editable after a fresh clone:

```bash
./.venv/Scripts/python.exe -m pip install -e . \
  -e packages/schemas -e packages/sqlserver -e packages/agents \
  -e packages/generators -e packages/validator -e packages/dbt_emit \
  -e packages/evals -e apps/worker -e apps/api
```

---

## Common commands

**ALWAYS invoke Python through the venv path**, not global. AppLocker allows `.venv/Scripts/python.exe` but the global Python doesn't have our packages.

```bash
# Lint + format + tests (run manually — pre-commit is dropped on this machine)
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format .
./.venv/Scripts/python.exe -m pytest packages/ -q       # 130 tests at M2-complete
./.venv/Scripts/python.exe -m pytest apps/api/tests -q  # 7 API tests (FakeLLM, offline, ~3s)

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

# Run the FastAPI service locally (M3). Requires GEMINI_API_KEY in .env to actually serve /map.
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
# OR via the project script entry point:
./.venv/Scripts/integration-agent-api.exe

# Smoke the API (no LLM cost — /health and /eval don't hit any provider):
curl -s localhost:8000/health | python -m json.tool
curl -s localhost:8000/eval | python -m json.tool
# CORS preflight from the M4 Next.js dev origin:
curl -i -X OPTIONS localhost:8000/map -H "Origin: http://localhost:3000" -H "Access-Control-Request-Method: POST"

# Run the Next.js frontend locally (M4.1). Defaults to http://localhost:3000.
# In one terminal: uvicorn (above). In another:
npm --prefix apps/web run dev               # dev server, hot reload
npm --prefix apps/web run lint              # ESLint flat config
npm --prefix apps/web run build             # production build (also type-checks)
# Override the API base URL via env var (.env.local in apps/web/):
#   NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
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
78d912a  Refresh CLAUDE.md for M4-complete state                          (137 tests)
998b52f  M4.3: HealthPill + /health page + responsive polish (M4 umbrella) (137 tests)
b76cbc1  M4.2: /map page with profile upload + long-request UX             (137 tests)
50fec54  M4.1: scaffold apps/web (Next.js 16 + Tailwind v4) + /eval pages  (137 tests)
9c30e9c  Add DESIGN.md and wire it into CLAUDE.md as the M4 UI reference   (137 tests)
7dc018f  Fill in M3-complete CLAUDE.md refresh hash                        (137 tests)
e262e7d  Refresh CLAUDE.md for M3-complete state                           (137 tests)
36a429f  M3: FastAPI service layer wrapping the M2 mapping graph           (137 tests)
b99b19f  Fill in M2-complete CLAUDE.md refresh hash                        (130 tests)
7557795  Refresh CLAUDE.md for M2-complete state                           (130 tests)
3ff37a7  M2.7: pipeline_dollars_total + ruff cleanup                       (130 tests)
a19810f  M2.6: Commutative-arg sorting in normalize_sql                    (128 tests)
94546da  M2.5: Add ClaudeProvider for Gemini-vs-Claude A/B                 (124 tests)
22ebf91  M2.4: Add SQL_EXEC_EQUIVALENT match level via DuckDB-executed SQL (120 tests)
479d44b  M2.3.x: JOIN-aware FK retrieval + sharper domain alignment 73.7%->78.9% (117 tests)
962d662  Fill in M2.3 CLAUDE.md refresh hash                                (114 tests)
07d3fd0  Refresh CLAUDE.md for M2.3-complete state                         (114 tests)
ac5feca  M2.3: Lift PATTERN/SQL_SEMANTIC to 100% exclusive via matcher domain alignment + classifier softening + k=15 (114 tests)
a856a09  Fill in M2.2 CLAUDE.md refresh hash                              (114 tests)
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

Tags: `m0-complete` on `afb7c6d`, `m1-code-complete` on `66db0a1`, `m1-complete` on `894ac59`, `m2.1..7-complete` (per-sub-milestone) and `m2-complete` on `3ff37a7`, `m3-complete` on `36a429f`, `m4.1-complete` on `50fec54`, `m4.2-complete` on `b76cbc1`, `m4.3-complete` on `998b52f`, **`m4-complete`** on `998b52f` (umbrella, latest).
Public repo: https://github.com/mohammad-alshaer/integration-agent — first push landed mid-M1 session.

---

## What's left — workstreams after M4

M4 is shipped (umbrella `m4-complete` on `998b52f`). The portfolio shape is end-to-end. Remaining work is **parallel/optional** — pick by what helps the Dar CIO demo or the resume narrative most. Ordered by impact-to-effort:

### M5 — deploy (THE LIKELY NEXT MILESTONE)

Get the demo onto a real URL so it's not just a localhost screenshot. Two pieces:
- **API**: deploy `apps/api` somewhere with persistent storage for `.duckdb/` and `.cache/`. Free-ish options: fly.io (free tier covers the volume) or Render (free tier). Both support a `Dockerfile` build with the existing pip install workflow. Need to bake `tmp/profiles/aw2022_filtered.json` + `tmp/profiles/awdw2022.json` and `benchmarks/adventureworks/samples/` into the image so demo runs work out of the box.
- **Web**: deploy `apps/web` to Vercel (the natural Next.js host, free tier). Set `NEXT_PUBLIC_API_BASE_URL` to the deployed API origin. Update `INTEGRATION_AGENT_API_CORS_ORIGIN` on the API to allow the Vercel preview URL.

Cost: ~$0/mo if Mohammad sticks to free tiers and the Gemini cache stays warm. First-run cold-cache eval on a fresh deploy could cost $0.30 if the eval runs.

### M3.1 — streaming progress for POST /map (small but high-impact)

Replace the M4.2 spinner-only UX with Server-Sent Events emitting per-node graph events ("semantic_matcher: 12 / 91", "validator: 3 retries", etc.). Web side renders an event log under the elapsed timer. ~150 LoC API, ~50 LoC web. Right call once any user actually runs a cold-cache /map and the 5min spinner UX gets noticed.

### Optional eval-side lifts (genuinely parallel)

- **JOIN-aware second-pass retrieval** to unlock TaxAmt + Freight EXACT (~30-50 LoC; documented in M2.3.x post-mortem). Would lift DERIVED 1/8 → 3/8 and headline 78.9% → ~83-85% inclusive. New eval reports surface in `/eval` automatically.
- **Real Claude A/B run** using the M2.5 ClaudeProvider — `python -m evals --provider claude --model claude-haiku-4-5` (~$0.30) — generates a side-by-side report. Side-by-side comparison in `/eval` is a nice portfolio screenshot.
- **CustomerKey domain-alignment regression** — matcher overgeneralizes Sales.Customer vs Person.BusinessEntity. ~15 LoC fix.

### M4.x — frontend polish (only if the demo demands it)

- **SQL syntax highlighting** in MappingSpecCard via `shiki` or `highlight.js` (~80 LoC + dep). Currently plain JetBrains Mono.
- **Auto-generated TS types** from `/openapi.json` via `openapi-typescript` (~10 LoC build hook). Replaces the hand-mirrored types in `apps/web/src/lib/api.ts`.
- **Save/export `MapResponse`** as JSON or markdown from the `/map` result panel.
- **JS-side tests** (Vitest + Playwright) when regressions actually appear. None today.

### M4 retrospective — what shipped, what didn't

Shipped: 6 routes, DESIGN.md-driven theme, profile-upload form with abort-able 10s–5min UX, eval browser with rates matrix, polled HealthPill + opt-in deep probe page, three sub-milestone commits + the umbrella `m4-complete` tag. Did NOT ship: shadcn primitives (hand-rolled small components instead — paid off), JS-side tests (deferred to M4.x), `/openapi.json` type auto-gen (deferred), streaming progress (M3.1), demo-profile auto-loader (M4.x).

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

10. **M2.2 regression fixed in M2.3.** ExtendedAmount → EXACT after adding the matcher's "Target table:" emphasis + domain-alignment system-prompt instruction. Generalizable lesson: the FQN-in-prompt isn't enough — the LLM weights an explicit "Target table:" labelled line more strongly.

11. **M2.3 partial-match softening + classifier robustness.** The classifier no longer falls back to `unsupported_in_m1` when a few-shot's canonical sources aren't all in candidates. Instead it emits `derived` with the available subset and a calibrated lower confidence (0.3-0.5). This produces useful PARTIAL matches — TaxAmt and DiscountAmount went from MISSING to PATTERN — but doesn't produce EXACT until retrieval surfaces the missing sources. Don't conflate the softening fix with a retrieval fix.

12. **Known M2.3 regression — CustomerKey.** Was EXACT in M2.2; is PATTERN in M2.3 because the matcher's domain-alignment instruction overgeneralizes to "prefer Person.BusinessEntity over Sales.Customer for the CustomerKey target." Both are technically valid (BusinessEntity is the FK parent of Customer), but the golden expects Customer. Documented as M2.X.b. The matcher's domain instruction needs sharpening — should fire for cross-domain mistakes (Purchasing vs Sales) but not for parent-vs-child within a domain.

13. **k=15 is now the matcher default** (was 10 through M2.2). Bumped in semantic_matcher.match_target_columns + graph.compile_graph + evals.RunnerConfig + evals CLI option. Matcher prompt grows ~50% in candidate-list tokens; cache-hit re-runs are unaffected; per-call cost increase is sub-cent. If you bump it again (e.g. to 20), update all 4 places.

14. **M2.3.x JOIN-aware FK retrieval is on by default.** When source_profile is supplied to match_target_columns (which graph.semantic_matcher_node now does), after the HNSW top-K we ALSO append type-compatible columns from FK-linked tables (max 3 per table, max 5 total extension). Distance is set to 0.999 for these — sorted last. The matcher's system prompt documents this so the LLM rerank knows the high-distance candidates are FK-extended and worth examining.

15. **M2.4 SQL_EXEC_EQUIVALENT match level requires sandbox.** scorer.classify_match accepts optional sandbox + source_profile kwargs; the eval runner now passes both. For non-EXACT specs whose actual SQL passed validation, the scorer builds canonical SQL from expected (RENAME → SELECT col, CONCAT → SELECT concat_ws), executes both against the sandbox, and compares result rows. DERIVED has no canonical synthesis (golden doesn't store the canonical expression) — falls through to SQL_SEMANTIC.

16. **M2.5 ClaudeProvider is implemented but no live A/B has run yet.** Run with `python -m evals --provider claude --model claude-haiku-4-5` — needs ANTHROPIC_API_KEY in .env. Estimated cost ~$0.30 cold-cache on Haiku 4.5, ~$1.50 on Sonnet 4.6. The structural unit tests (test_llm.py) mock the SDK so they're free.

17. **M2.7 pipeline_dollars_total** uses pricing from `packages/evals/src/evals/pricing.py`. If a provider returns 0 dollars, check the PRICING dict for that (provider, model) pair — unknown pairs default to (0.0, 0.0). Update PRICING if a provider changes their published pricing.

18. **M3 lifespan tolerates missing API keys.** `apps/api/src/api/main.py` wraps the deps construction in try/except — if `GEMINI_API_KEY` (or `EMBEDDING_PROVIDER`-equivalent) is unset, lifespan logs a warning and stores `app.state.deps = None`. Routes 503 in that state. Tests rely on this: they construct `TestClient(app)` **without** the `with` context (so lifespan never runs) and override `get_deps` via `app.dependency_overrides`. If you switch tests to `with TestClient(app)`, lifespan will try to build a real `GeminiProvider` and the test will fail without a real key.

19. **All `/map` requests serialize through one `asyncio.Lock`.** `apps/api/src/api/routers/map.py` holds `deps.map_lock` for the entire `_run_graph_sync` call because (a) the shared `SourceVectorStore` DuckDB connection isn't thread-safe and (b) `GeminiProvider`'s running token totals get clobbered by concurrent writers. Real concurrency needs per-request connections + per-request LLMClient — M4 territory if needed.

20. **CORS allow-origin is `http://localhost:3000`** (the M4 Next.js dev server) — set in `apps/api/src/api/config.py:Settings.cors_origin`. Override via `INTEGRATION_AGENT_API_CORS_ORIGIN` env var. M5 will need real origins (and probably auth) when the API leaves localhost.

21. **`store.add_columns(req.source_profile)` runs on every `/map` request.** Embedder content cache makes repeat embeddings free; the HNSW rebuild is sub-second for AdventureWorks (~500 columns). `rebuild_index=true` in the body additionally calls `store.reset()` first. If you ever pin a single source profile per process and want to skip this, gate behind a profile-hash check — but the current behavior is correct (each request reflects its profile) at trivial cost.

22. **Eval lookup globs `benchmarks/*/out/eval_report*.json`** (`apps/api/src/api/eval_lookup.py`) with a 60s in-memory TTL cache. The eval runner stays untouched; existing baseline files (`eval_report.m1-baseline.json`, `eval_report.m2-complete.json`, etc.) are discovered for free. If you ever delete or rename a report file mid-conversation, call `eval_lookup.invalidate_cache()` or wait 60s.

23. **`apps/web/` is Next.js 16 + React 19 + Tailwind v4** (NOT v14/v3 from training data). Breaking-change cheatsheet: (a) `params` in dynamic routes is `Promise<{...}>` — must `await params` (use `PageProps<'/eval/[run_id]'>` helper). (b) Tailwind theme lives in `src/app/globals.css` `@theme inline {}` block, not `tailwind.config.ts` (no JS config file is generated). Color/font/shadow tokens are defined as CSS custom properties (`--color-*`, `--font-*`, `--shadow-*`) and become utilities automatically. (c) ESLint flat config (`eslint.config.mjs`), Next config in TS (`next.config.ts`). (d) The bundled docs at `apps/web/node_modules/next/dist/docs/` are the authoritative breaking-change reference — read them before diverging from generated patterns.

24. **abcDiatype is paid (ABC Dinamo) — Geist Sans is the substitute.** `apps/web/src/app/layout.tsx` wires `Geist` (sans) + `JetBrains_Mono` (mono) via `next/font/google` — Geist is geometric sans-serif, closer to abcDiatype than Inter. Documented in DESIGN.md as the substitution. JetBrains Mono is loaded exactly as DESIGN.md specifies.

25. **`apps/web` TS types are hand-mirrored from Python contracts** in `apps/web/src/lib/api.ts` — `EvalSummary`, `EvalReport`, `ScoreEntry`, `MatchLevel`, `Pattern`. The file's header comment lists the Python source-of-truth paths. If you rename a Python field, update both sides. Auto-generation from `/openapi.json` is M4.x.

26. **Next.js dev defaults to port 3000; CORS in the API only allows `http://localhost:3000`.** Don't change either independently. If the dev server can't bind 3000 (already taken), set `INTEGRATION_AGENT_API_CORS_ORIGIN=http://localhost:<other>` on the API process to keep them aligned.

27. **shadcn was deliberately skipped through M4.** All `apps/web/src/components/` are hand-rolled in pure Tailwind utility classes (Brand, Container, Card, PageHeader, DataTable, Badge, Spinner, ProfileUploader, Select, NumberField+Toggle, MappingSpecCard, HealthPill). Re-theming shadcn primitives to DESIGN.md was estimated heavier than hand-rolling at the M4 component count. Add shadcn in M4.x only when richer interactions (Dialog, Toast, Command palette, Accordion) genuinely earn their keep.

28. **React 19 / Next 16 lint rule: `react-hooks/set-state-in-effect`.** The rule rejects synchronous `setState` calls inside `useEffect` bodies — they cause cascading renders. Pattern fixes: (a) move the `setState` into the event handler that triggers the effect (e.g. `setElapsed(0)` before `setSubmitting(true)` in onSubmit, not at the top of the elapsed-tick effect); (b) for "reset state when prop changes," do it in the wrapper handler that sets the prop (e.g. `handleTargetLoad = (p) => { setTarget(p); setTargetTable(""); }` instead of `useEffect(() => setTargetTable(""), [target])`). Encountered this twice in `apps/web/src/app/map/page.tsx`.

29. **HealthPill polls `GET /health` every 30s from the browser.** Cheap (no LLM call). The pill shows the LLM provider label (e.g. "gemini") on success, "offline" or "api 503" on failure. Lives in the Brand header on every page. The dedicated `/health` page has the opt-in deep probe — that one DOES burn one Gemini cache slot per click; default off, explicit user action only.

30. **`apps/web/AGENTS.md` is generated by create-next-app and warns "this is NOT the Next.js you know."** Take it seriously — the bundled docs at `apps/web/node_modules/next/dist/docs/` are the authoritative breaking-change reference. Most likely-to-bite changes already encoded in gotchas #23 (params Promise, Tailwind v4 CSS-first) + #28 (set-state-in-effect).

---

## When in doubt

1. **For M5 (deploy) work:** read the "What's left" section above. The API needs a Dockerfile + persistent volume for `.duckdb/` and `.cache/`; the web app deploys to Vercel with `NEXT_PUBLIC_API_BASE_URL` set to the API URL. Update `INTEGRATION_AGENT_API_CORS_ORIGIN` to the deployed Vercel origin so CORS still passes. Test profiles + Parquet samples need to be baked into the API image.
2. **For M4 / web edits:** **read `DESIGN.md` first** — it's the design-system contract. The hand-mirrored TS types in `apps/web/src/lib/api.ts` are the only place to update if the Python contracts in `packages/schemas/` or `packages/evals/` change. Components are hand-rolled in pure Tailwind; shadcn was deliberately skipped (gotcha #27). React 19's `react-hooks/set-state-in-effect` rule blocks synchronous `setState` calls inside `useEffect` bodies (gotcha #28).
3. **For M3 (API) edits:** the canonical references are `apps/api/src/api/main.py` (lifespan + CORS), `apps/api/src/api/routers/{health,map,eval}.py`, and `docs/adr/0005-fastapi-service-layer.md`. The 7 offline tests in `apps/api/tests/test_routes.py` are the contract guard.
4. **For project history:** the M1 plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md`, the M2-evolution plan at `~/.claude/plans/continue-with-m2-1-from-lexical-barto.md` (covers M2.1 → M2.7), and the M4 plan at `~/.claude/plans/lets-start-working-on-refactored-prism.md` (covers M4.1 explicitly; M4.2 + M4.3 done without separate plan files) are reference-only. M3 history lives in commit messages + `docs/adr/0005-fastapi-service-layer.md`.
5. **Memory:** check `MEMORY.md` for project/feedback notes about Mohammad's preferences and corporate environment specifics.
6. **For DataOps / Claude-specific concept questions**, explain foundational concepts (eval, RAG, dbt, embeddings, LangGraph state machines, React Server Components, etc.) with a concrete example tied to the current task. Mohammad is a new-grad — don't just name-drop.
7. **Cost discipline:** Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision. Gemini Flash paid tier-1 is already configured (~$0.30/full eval; cache makes re-runs nearly free). Frontend is $0 (Vercel free tier).
8. **Before any GitHub push:** verify no secrets in the diff. The repo is **public**; anything pushed is permanently visible.
