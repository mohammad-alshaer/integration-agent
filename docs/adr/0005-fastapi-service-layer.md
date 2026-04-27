# ADR 0005 — FastAPI service layer (M3)

## Status

Accepted — 2026-04-27. Implemented as `apps/api/`.

## Context

M2 wrapped at 78.9% inclusive / 96.7% exclusive EXACT on AdventureWorks. The original stack plan calls for **FastAPI in M3** and **Next.js + shadcn in M4**. Until now the mapping graph was reachable only via the `worker run` Typer CLI, which assumes a local Python venv with all workspace packages installed and the `.cache/llm` + `.cache/embeddings` + `.duckdb/` directories writable. M4's browser UI cannot satisfy any of those constraints.

The portfolio framing for the Dar CIO meeting also shifts here: from "how accurate is the classifier" (an M2-era question) to **"the agent runs as a service that humans + downstream systems can call."**

## Decision

Ship a thin FastAPI wrapper around the existing `agents.graph.build_graph()` compiled `StateGraph`. Four endpoints, no auth, file-glob lookup for eval reports, single target table per request, sync handler in a thread pool.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + provider/model surface; `?deep=true` opts in to a 1-call LLM round-trip |
| `POST` | `/map` | Wrap `graph.invoke()` for one target table; return specs + classifications + validation summary |
| `GET` | `/eval` | List `EvalSummary` for every parseable `benchmarks/*/out/eval_report*.json` |
| `GET` | `/eval/{run_id}` | Return the full `EvalReport` whose `run_id` field matches the path param |

### Concrete choices

1. **Sync handler in `asyncio.to_thread` with hard timeout (default 600s).** `GeminiProvider.structured()`, `GeminiEmbedder.embed()`, and DuckDB are all synchronous; running them inline would block the event loop for the full 10s–5min latency. Wrapping in `to_thread` releases the loop without forcing an async LLM rewrite. A `TimeoutError` becomes a `504`.
2. **Single target table per request.** Bounds the worst-case timeout. Multi-table fan-out is the caller's responsibility (the M4 UI submits N requests in parallel, each on its own thread-pool slot).
3. **Inline `SchemaProfile` JSON in the request body.** A browser caller has no shared filesystem with the server. AdventureWorks profiles are ~3-5 MB JSON — well under FastAPI's default body limits.
4. **Single global `asyncio.Lock` serializes `/map` requests.** DuckDB connections (held by `SourceVectorStore`) are not thread-safe; nor is `GeminiProvider`'s running token-count state. A connection pool / per-request connection is M4-or-later if real concurrency is needed.
5. **Source-vector store rebuilt on every request via `store.add_columns(profile)`.** The embedder content cache makes repeat embeddings free, and the HNSW index rebuild is sub-second for AdventureWorks-sized profiles. `rebuild_index=True` additionally calls `store.reset()` first — useful when a profile changed shape.
6. **Eval lookup is `glob('*/out/eval_report*.json')` + parse + 60s in-memory TTL cache.** The eval runner stays untouched; existing baseline files (`eval_report.m2-complete.json`, etc.) are discovered for free. N is ~10; parse cost is microseconds.
7. **CORS allows `http://localhost:3000`** so M4's Next.js dev server plugs in cleanly. Configurable via `INTEGRATION_AGENT_API_CORS_ORIGIN`.
8. **Deep health probe is opt-in (`?deep=true`).** Burns one LLM round-trip per call; default off so monitors don't accidentally drain quota.
9. **Lifespan tolerates missing env vars.** Without `GEMINI_API_KEY` the lifespan logs a warning and stores `app.state.deps = None`; routes return 503. Tests override `get_deps` via `app.dependency_overrides` and never hit the lifespan path (the `TestClient` is constructed without the `with` context).

## Rejected alternatives

- **Async-with-job-IDs (`POST /map/jobs` returns `job_id`, client polls).** Cleaner UX for long requests but adds a job table, a status route, and background worker plumbing. Out of scope for M3; revisit when M4 needs streaming progress.
- **Profile file paths in the request body.** Smaller bodies but assumes a shared FS — fundamentally incompatible with a browser caller. Even for the local CLI demo, a path-based contract would need a separate JSON contract for M4.
- **Forward-only writes to `apps/api/data/runs/{run_id}.json`.** More disciplined long-term storage but creates two write paths (the existing `evals.runner` writer and a new API-side writer) for the same artifact. Not worth the maintenance for M3 sizes.
- **`POST /profile`.** The `worker profile` path connects to SQL Server and runs LLM enrichment for 5–30 min; HTTP is the wrong shape. Stays CLI-only.
- **`POST /eval` to trigger an eval run.** Even longer than `/map` (hits the full golden set). Kept as a CLI-only operation (`python -m evals`); the API only reads.

## Consequences

- **504s on cold-cache full-eval-sized requests are expected and visible** — the timeout surfaces the real performance envelope. M4 will need streaming + jobs to UX around this.
- **One `/map` request per CPU core's worth of compute, not per concurrent user.** The single global lock means a slow request blocks all others; for a local-only demo this is fine. Real multi-tenancy needs per-request DuckDB connections + a per-request `LLMClient` instance (the latter to avoid token-count contention).
- **Eval discoverability follows `EvalReport.run_id` (timestamp-based).** Listing is O(N) parse where N is the number of files under `benchmarks/*/out/`; if that ever exceeds a few hundred, switch to a forward-only index file or a small SQLite catalog.
- **No persistence of `MappingSpec` results beyond the response body.** Callers that want to keep a result archive it themselves; the API is stateless w.r.t. /map outputs. M4's UI will likely add a "save run" button that POSTs the response to a new endpoint — not in scope here.
- **`truststore.inject_into_ssl()` ordering is load-bearing.** Same pattern as `apps/worker/src/worker/cli.py`: must execute before any module that constructs a `google.genai` client. Encoded as the first non-comment statement in `apps/api/src/api/main.py` with `# noqa: E402` on every post-inject import.
