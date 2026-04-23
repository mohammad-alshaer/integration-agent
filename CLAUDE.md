# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** M1 Week 3 complete (11 commits on `main`, tag `m0-complete` on the M0 head). W4 next — Validator + dbt_emit + evals + first accuracy number. The full LangGraph pipeline (Schema Explorer → Semantic Matcher → Pattern Classifier → Transformation Generator) is wired and produces real `MappingSpec` artifacts offline via `scripts/smoke_graph.py`.

**Canonical plan:** `C:\Users\mfalshaer\.claude\plans\i-want-to-do-jiggly-yeti.md` — read this before any non-trivial work. W4 is split into W4-A (validator), W4-B (dbt_emit), W4-C (evals + golden set), W4-D (CLAUDE.md + m1-code-complete tag), W4-E (real-LLM accuracy number, quota-gated). Always edit the plan incrementally when scope shifts; don't drift silently.

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
| **Gemini 2.5 Flash free tier = 20 requests per DAY** (hard cap — not per-minute as one might assume) | Prompt-hash cache is the #1 defense — repeated runs burn ~0 quota on unchanged prompts. For full-scale eval runs: (a) wait for daily reset, (b) add Google AI Studio billing (~$0.30/full eval on Flash tier-1 at 1000 RPM), or (c) swap provider via `LLMClient` (a ~15-line `ClaudeProvider` would cost ~$0.10/run on Haiku 4.5). |
| **Gemini embedding free tier ~100 req/min** (not obvious from docs) | `GeminiEmbedder` has `inter_batch_delay_sec=1.0` by default + exponential retry up to 32s. |
| Voyage embeddings without a payment method (hard cap: 3 RPM / 10K TPM) | **Default embedder is Gemini, not Voyage.** Use Voyage only if a payment method is on file (still 200M free tokens). Set `EMBEDDING_PROVIDER=voyage` to switch. |

**Bash sandbox quirks** (separate from AppLocker — it's the Claude tool shell's allowlist): `cat`, `wc`, `head`, `grep`, `tail`, `mkdir` are blocked. Workarounds:
- `git commit -m "..." -m "..."` multi-flag instead of HEREDOCs.
- Use the Write tool for file content, never `echo >` or `cat <<EOF`.
- Skip pipes to `head`/`tail`/`grep`; run the command raw.
- Use Python for `mkdir` (or the Write tool implicitly creates parent dirs).

**What works:** Python (whitelisted), `.venv/Scripts/*` binaries, SQL Server 2025 Developer Edition (instance `SQLDEV2025`) via ODBC Driver 18 with Windows auth, DuckDB in-process, Git, pip (recent pip auto-uses truststore), Voyage/Google embeddings via `truststore`.

---

## Stack

- **Python 3.11** + `.venv/` + pip (no uv)
- **LangGraph** (`>=0.2,<0.3`) for multi-agent orchestration — wired in W3 (`packages/agents/src/agents/graph.py`)
- **Gemini 2.5 Flash** via `google-genai` SDK — default LLM, abstracted behind `LLMClient` protocol in `packages/agents/src/agents/llm.py`; provider-swappable
- **Gemini `gemini-embedding-001`** as default embedder (1024 dims via `output_dimensionality`); `VoyageEmbedder` with `voyage-3-large` as the alternative. Both sit behind the `Embedder` protocol and share a SHA-256 content cache under `.cache/embeddings/`.
- **DuckDB + `vss` HNSW** — unified metadata + vector + sandbox store (`.duckdb/integration_agent.duckdb`)
- **SQL Server 2025 Developer Edition** — source of truth (AdventureWorks 2022 restored: `AdventureWorks2022` + `AdventureWorksDW2022`)
- **dbt** models as output (`dbt-duckdb` adapter in M1-M3, `dbt-sqlserver` later in M4+)
- **Langfuse** cloud free tier for LLM observability
- **FastAPI** (M3+), **Next.js 14** + shadcn/ui (M4+)
- **Pydantic v2** for every contract between specialists (see `packages/schemas/`)

---

## Repo layout (as of end of W3)

```
Integration-Agent/
├── .venv/                           gitignored; AppLocker-allowed Python binaries
├── .duckdb/                         gitignored; unified metadata + vector file
├── .cache/
│   ├── llm/                         gitignored; SHA-256 prompt-hash LLM output cache
│   └── embeddings/                  gitignored; per-text embedding cache
├── .env                             gitignored; API keys (GEMINI, LANGFUSE, VOYAGE)
├── .env.example                     template (committed; no secrets)
├── pyproject.toml                   single root; deps + ruff/mypy/pytest config
├── CLAUDE.md                        this file
│
├── scripts/
│   ├── check_sqlserver.py           SQL Server connectivity + DB list
│   ├── verify_adventureworks.py     row-count assertions vs MS published numbers
│   ├── check_duckdb.py              DuckDB + vss HNSW smoke test
│   ├── hello_gemini.py              Gemini + Langfuse structured-output smoke test
│   ├── smoke_embeddings.py          Voyage/Gemini + vector store smoke test on AW subset
│   └── smoke_graph.py               FakeLLM-driven end-to-end graph run — emits 4 MappingSpecs
│
├── apps/
│   └── worker/                      typer CLI (integration-agent-worker)
│                                    subcommands: profile, run, version
│
├── packages/
│   ├── schemas/                     Pydantic contracts: profile, candidates, patterns,
│   │                                mapping, validation, trace. The contract between specialists.
│   ├── sqlserver/                   connect, introspect (INFORMATION_SCHEMA + sys.extended_properties),
│   │                                profile_stats (null/distinct/min/max/top_values),
│   │                                sample (FK-closure → Parquet), redaction (PII masking)
│   ├── agents/                      LLMClient + GeminiProvider + SHA-256 cache, Embedder + Voyage/Gemini,
│   │                                vector_store (DuckDB+vss), schema_explorer, semantic_matcher,
│   │                                pattern_classifier, transformation_generator, graph (LangGraph assembly)
│   ├── generators/                  PatternGenerator Protocol + Rename/Concat/Derived implementations
│   ├── validator/                   [W4-A — NOT YET] DuckDB sandbox + error-hint normalizer
│   ├── dbt_emit/                    [W4-B — NOT YET] dbt_project.yml + schema.yml + stg_*.sql writers
│   └── evals/                       [W4-C — NOT YET] golden set loader + scorer + runner
│
├── benchmarks/
│   └── adventureworks/
│       ├── samples/                 gitignored; Parquet samples from FK-closure sampler
│       ├── expected_mappings.yaml   [W4-C — NOT YET] hand-authored ground truth
│       └── out/                     gitignored; dbt project + eval report output
│
├── docs/adr/                        0001-langgraph, 0002-duckdb-unified-store,
│                                    0003-duckdb-parquet-sandbox, 0004-prompt-hash-caching
│
├── tmp/                             gitignored; ad-hoc profile + mapping outputs
└── description.txt                  Mohammad's original project description
```

Each `packages/*/` has its own `pyproject.toml`. Install every workspace package editable:
```bash
./.venv/Scripts/python.exe -m pip install -e . \
  -e packages/schemas -e packages/sqlserver -e packages/agents \
  -e packages/generators -e apps/worker
# (add -e packages/validator -e packages/dbt_emit -e packages/evals as they land in W4)
```

---

## Common commands

**ALWAYS invoke Python through the venv path**, not global. AppLocker allows `.venv/Scripts/python.exe` but the global Python doesn't have our packages.

```bash
# Lint + format + tests (run manually — pre-commit is dropped on this machine)
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format .
./.venv/Scripts/python.exe -m pytest packages/ -v

# Smoke tests (all should be green; no LLM quota touched by graph/smoke_graph)
./.venv/Scripts/python.exe scripts/check_sqlserver.py
./.venv/Scripts/python.exe scripts/verify_adventureworks.py
./.venv/Scripts/python.exe scripts/check_duckdb.py
./.venv/Scripts/python.exe scripts/hello_gemini.py       # 1 LLM call (quota!)
./.venv/Scripts/python.exe scripts/smoke_embeddings.py   # Voyage/Gemini embedding quota
./.venv/Scripts/python.exe scripts/smoke_graph.py        # FakeLLM — zero network, zero quota

# Profile a database → SchemaProfile JSON (first step of any mapping run)
./.venv/Scripts/python.exe -m worker profile \
  --db AdventureWorks2022 --role source --out ./tmp/profiles/aw2022.json \
  [--no-enrich] [--no-include-samples] [--rate-limit-delay 6.5]

# Run the W3 mapping graph (real LLM — watch the 20-req/day Gemini Flash cap)
./.venv/Scripts/python.exe -m worker run \
  --source-profile ./tmp/profiles/aw2022.json \
  --target-profile ./tmp/profiles/awdw2022.json \
  --target-table dbo.DimCustomer \
  --rebuild-index --rate-limit-delay 6.5 \
  --out ./tmp/profiles/mappings_dimcustomer.json

# [W4] dbt build verification — DuckDB adapter against the Parquet sample sources
./.venv/Scripts/python.exe -m dbt build \
  --project-dir benchmarks/adventureworks/out/dbt \
  --profiles-dir ./profiles

# [W4] Eval harness — produces the first-accuracy-number JSON report
./.venv/Scripts/python.exe -m evals run \
  --pair adventureworks --provider gemini --model gemini-2.5-flash
```

---

## Conventions

**Structure:**
- Contracts live in `packages/schemas/` — never let ad-hoc dicts leak between specialists. Use Pydantic v2 everywhere.
- LLM calls ALWAYS go through `LLMClient.structured()`. It enforces prompt-hash caching, provider swappability, retry-with-backoff on 429/5xx, and cost metadata attachment.
- **Two confidences — never merged:** `llm_confidence` (model self-report) and `validation_pass_rate` (measured in DuckDB sandbox — filled in by the W4 validator). UI/logs show both.
- dbt output lives under `benchmarks/<pair>/out/dbt/`. Every generated `.sql` line carries a tail comment: `-- pattern=<p>; source(s)=<fqn,fqn>; llm_conf=<0-1>; pass_rate=<0-1>`.
- **Pattern scope discipline is visible in code:** `Pattern.UNSUPPORTED_IN_M1` is an explicit enum value the classifier emits for any non-M1 pattern. The transformation_generator dispatcher skips those with a log line. Don't stub fake generators for SPLIT/CONSTANT/etc.

**LLM / network code:**
- Any script that opens an HTTPS connection starts with:
  ```python
  import truststore
  truststore.inject_into_ssl()
  ```
  Before the imports that construct HTTPS clients. Subsequent imports get `# noqa: E402`.
- Don't read `.env` into the conversation; scripts load it via `python-dotenv`.
- Default to `gemini-2.5-flash`. Model name is read from `GEMINI_MODEL` env var — upgrade to Pro is a billing decision, not a code change.
- Default embedder is `GeminiEmbedder` (`EMBEDDING_PROVIDER=gemini`). Voyage is an alternative.
- **Hallucination guards:** both Semantic Matcher and Pattern Classifier post-filter their LLM output against the retrieved candidate set. Any `source_fqn` that wasn't in the retrieved top-K gets dropped with a log warning.

**Testing + offline verification:**
- **`FakeLLM` pattern:** unit tests and `scripts/smoke_graph.py` implement the `LLMClient` Protocol with a class that returns scripted responses. This keeps test runs fast, provider-agnostic, and independent of API quotas / provider uptime. Example: `packages/agents/tests/test_pattern_classifier.py::FakeLLM`, `packages/generators/tests/test_derived.py::FakeLLM`, `scripts/smoke_graph.py::FakeLLM`.
- **Live integration tests** (e.g. `packages/sqlserver/tests/test_introspect.py`) use `pytest.mark.skipif(not _server_reachable(), ...)` so fresh clones without SQLDEV2025 don't fail.
- Don't rely on real-LLM runs in pytest — prompt-hash cache makes them "free on re-run" but first-run quota burn is real.

**Git workflow:**
- Milestone commits = multiple-letter sub-milestones (e.g. `M1 W3-A`, `M1 W3-B`, ...). Each sub-milestone is a single commit. Commit messages use multiple `-m` flags (Bash sandbox blocks HEREDOC-with-cat).
- Every commit ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Milestones tagged: `m0-complete`, planned `m1-code-complete` (end of W4-D) and `m1-complete` (after W4-E real-LLM eval).
- Branch: `main` (renamed locally from `master`; no global git config changes).
- No pushes yet — no remote configured.

**Code style:**
- ruff enforces: line-length 100, select=`["E","F","I","W","B","UP","SIM"]`, ignore=`["E501","B008"]` (B008 ignored because typer's `typer.Option(...)` defaults are safe).
- Default to no comments. Write `# why` only when the reason is non-obvious.
- Never write multi-paragraph docstrings. One short line per function.
- Python 3.11 idioms: `from __future__ import annotations`, `|` unions, `list[T]`/`dict[K,V]` generics, `StrEnum`.

---

## Current status & next steps

**M0 — complete** (tag `m0-complete` on `afb7c6d`). 6 commits.

**M1 — in progress**:
- ✅ **W2 complete** — Schema Explorer (`d698c40`, `0ceb1b1`). Introspection + profile stats + FK-closure sampler + PII redaction + LLM enrichment. 25 tests.
- ✅ **W3 complete** — embeddings + vector store + Semantic Matcher + Pattern Classifier + 3 generators + LangGraph + `worker run` + offline smoke. 4 commits (`b2e5861`, `81dda7b`, `d266fed`, `4832a5d`). 47 tests. `scripts/smoke_graph.py` emits 4 MappingSpecs covering all 3 M1 patterns offline.
- 🔨 **W4 — starting now**. Validator + dbt_emit + evals + first accuracy number. Split into W4-A/B/C offline code (no quota needed), W4-D doc refresh + `m1-code-complete` tag, W4-E real-LLM accuracy number (quota-gated).

---

## When in doubt

1. Re-read the plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md`.
2. Check `MEMORY.md` for project/feedback notes.
3. For DataOps concept questions or Claude-specific how-tos, ask Mohammad — he's a new-grad, so explain foundational concepts (eval, RAG, dbt, embeddings, LangGraph state machines, etc.) with a concrete example tied to the current task. Don't just name-drop.
4. Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision.
