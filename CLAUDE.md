# Integration-Agent — Claude Code project notes

Multi-agent AI system that automates schema mapping + dbt-model generation for data integration (OLTP → analytical warehouse). Primary benchmark: **AdventureWorks OLTP → AdventureWorksDW**. Built as a personal portfolio project by Mohammad Falshaer (new-grad DataOps engineer, Dar Al-Handasah) to showcase at Dar's weekly CIO AI-agent meeting.

**Current milestone:** M0 complete (tag `m0-complete`, 6 commits). M1 next — Schema Explorer + Semantic Matcher + 3 pattern generators + Validator + dbt emission + eval harness → first AdventureWorks accuracy number.

**Canonical plan:** `C:\Users\mfalshaer\.claude\plans\i-want-to-do-jiggly-yeti.md` — read this before any non-trivial work. Always edit the plan incrementally when scope or approach shifts; don't drift from it silently.

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
| Python default TLS (certifi bundle doesn't trust corporate CA) | **`truststore.inject_into_ssl()` at top of any script making HTTPS calls**, before any HTTPS client is constructed. Already wired into `scripts/hello_gemini.py`. |
| Gemini 2.5 Pro free tier (quota = 0 on this account) | Use `gemini-2.5-flash`. `.env.example` defaults to Flash. |

**Bash sandbox quirks** (separate from AppLocker — it's the Claude tool shell's allowlist): `cat`, `wc`, `head`, `grep`, `tail` are blocked. Workarounds:
- `git commit -m "..." -m "..."` multi-flag instead of HEREDOCs.
- Use the Write tool for file content, never `echo >` or `cat <<EOF`.
- Skip pipes to `head`/`tail`/`grep`; run the command raw.

**What works:** Python (whitelisted), `.venv/Scripts/*` binaries, SQL Server 2025 Developer Edition (instance `SQLDEV2025`) via ODBC Driver 18 with Windows auth, DuckDB in-process, Git, pip (recent pip auto-uses truststore).

---

## Stack

- **Python 3.11** + `.venv/` + pip (no uv)
- **LangGraph** (pinned `>=0.2,<0.3`) for multi-agent orchestration (arriving M1 Week 3)
- **Gemini 2.5 Flash** via `google-genai` SDK, free tier — abstracted behind `LLMClient` protocol in `packages/agents/src/agents/llm.py`; provider-swappable
- **Voyage `voyage-3-large`** for embeddings, free tier (used from M1 Week 3)
- **DuckDB + `vss`** as unified metadata + vector + sandbox store
- **SQL Server 2025 Developer Edition** as the benchmark source of truth (AdventureWorks 2022 restored)
- **dbt** models as output (dbt-duckdb adapter M1-M3, dbt-sqlserver later)
- **Langfuse** cloud (free tier) for LLM observability
- **FastAPI** (M3+), **Next.js 14** + shadcn/ui (M4+)
- **Pydantic v2** for every contract between specialists (see `packages/schemas/`)

---

## Repo layout

```
Integration-Agent/
├── .venv/                     gitignored; AppLocker-allowed Python binaries
├── .duckdb/                   gitignored; unified metadata + vector file
├── .cache/llm/                gitignored; SHA-256 prompt-hash output cache
├── .env                       gitignored; API keys (GEMINI, LANGFUSE, VOYAGE)
├── .env.example               template (committed; no secrets)
├── pyproject.toml             single root; deps + ruff/mypy/pytest config
├── scripts/
│   ├── check_sqlserver.py     SQL Server connectivity + DB list
│   ├── verify_adventureworks.py  row-count assertions
│   ├── check_duckdb.py        DuckDB + vss HNSW smoke test
│   └── hello_gemini.py        Gemini + Langfuse structured-output smoke test
├── packages/
│   ├── schemas/               Pydantic contracts (profile, candidates, patterns, mapping, validation, trace)
│   └── agents/                LLMClient Protocol + GeminiProvider + prompt-hash cache
│                              (M1 will add: schema_explorer, semantic_matcher, pattern_classifier,
│                               transformation_generator, validator, graph.py, embeddings.py)
├── docs/adr/                  0001-langgraph, 0002-duckdb-unified-store,
│                              0003-duckdb-parquet-sandbox, 0004-prompt-hash-caching
└── description.txt            Mohammad's original project description
```

Packages are installed editable with `pip install -e packages/schemas -e packages/agents`. Each has its own `pyproject.toml`.

---

## Common commands

**ALWAYS invoke Python through the venv path**, not global. AppLocker allows `.venv/Scripts/python.exe` but the global Python doesn't have our packages.

```bash
# Install root project + all workspace packages editable
./.venv/Scripts/python.exe -m pip install -e . -e packages/schemas -e packages/agents

# Lint + format (pre-commit is dropped on this machine; run these manually)
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format .

# Tests
./.venv/Scripts/python.exe -m pytest

# M0 smoke tests (all should be green)
./.venv/Scripts/python.exe scripts/check_sqlserver.py
./.venv/Scripts/python.exe scripts/verify_adventureworks.py
./.venv/Scripts/python.exe scripts/check_duckdb.py
./.venv/Scripts/python.exe scripts/hello_gemini.py
```

---

## Conventions

**Structure:**
- Contracts live in `packages/schemas/` — never let ad-hoc dicts leak between specialists. Use Pydantic v2 everywhere.
- LLM calls ALWAYS go through `LLMClient.structured()` in `packages/agents/src/agents/llm.py`. This enforces prompt-hash caching, cost tracking, and provider swappability.
- Two confidences — never merged: `llm_confidence` (model self-report) and `validation_pass_rate` (measured in DuckDB sandbox). UI/logs show both.
- dbt output lives under `benchmarks/<pair>/out/dbt/`. Every generated `.sql` line carries a tail comment: `-- pattern=<p>; source(s)=<fqn,fqn>; llm_conf=<0-1>; pass_rate=<0-1>`.

**LLM / network code:**
- Any script that opens an HTTPS connection starts with:
  ```python
  import truststore
  truststore.inject_into_ssl()
  ```
  Before the imports that construct HTTPS clients. Subsequent imports get `# noqa: E402`.
- Don't read `.env` into the conversation; scripts load it via `python-dotenv`.
- Default to `gemini-2.5-flash`. Upgrading to Pro is a billing decision, not a code change — model is read from `GEMINI_MODEL` env var.

**Git workflow:**
- Each milestone = one commit (at minimum). Commit messages use multiple `-m` flags (the Bash sandbox blocks HEREDOC-with-cat).
- Every commit ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Milestones tagged: `m0-complete`, later `m1-complete`, etc.
- Branch: `main` (renamed locally from `master`; no global git config changes).
- No pushes yet — no remote configured.

**Code style:**
- ruff enforces: line-length 100, select=`["E","F","I","W","B","UP","SIM"]`. Run `ruff format .` before committing.
- Default to no comments. Write `# why` only when the reason is non-obvious (e.g. the truststore block).
- Never write multi-paragraph docstrings. One short line per function.
- Python 3.11 idioms: `from __future__ import annotations`, `|` unions, `list[T]`/`dict[K,V]` generics, `StrEnum`.

---

## Current status & next steps

**M0 — complete** (tag `m0-complete` on `afb7c6d`). Six commits on main.

**M1 — Weeks 2-4**: first accuracy number on AdventureWorks OLTP → AdventureWorksDW using 3 patterns (1:1 rename, N:1 concat, derived/computed). No UI, no FastAPI — CLI only.

- **Week 2 (next):** Schema Explorer. Build `packages/sqlserver/` (introspect + FK-closure Parquet sampler + PII redaction) and `packages/agents/src/agents/schema_explorer.py` (LLM pass that enriches each `ColumnProfile` with `inferred_semantic_type` + `quality_flags`).
- **Week 3:** Semantic Matcher + Pattern Classifier + 3 generators + LangGraph assembly.
- **Week 4:** Validator (DuckDB sandbox + retry-with-error-hints) + dbt emission + `packages/evals/` (golden set + scorer + runner) + first accuracy number.

**Classifier escape hatch:** Pattern enum includes `UNSUPPORTED_IN_M1` explicitly — the 6 non-M1 patterns are flagged as gaps and tracked; do NOT stub them with fake generators. Scope discipline is visible in the code.

---

## When in doubt

1. Re-read the plan at `~/.claude/plans/i-want-to-do-jiggly-yeti.md`.
2. Check `MEMORY.md` for project/feedback notes.
3. For DataOps concept questions or Claude-specific how-tos, ask Mohammad — he's a new-grad, so explain foundational concepts (eval, RAG, dbt, embeddings, etc.) with a concrete example tied to the current task. Don't just name-drop.
4. Mohammad prefers free/free-tier solutions; surface cost estimates upfront on any paid-service decision.
