# ADR 0004 — Idempotency via SHA-256 prompt-hash output caching

**Status:** Accepted (2026-04-23)

**Context.** The plan asks for idempotency — same input produces same output — as a production-grade requirement. The naive approach is to set `temperature=0` (or equivalent) and pass a seed. Empirically, LLM outputs at every major provider (Anthropic, Google, OpenAI) are **not** deterministic even with temperature=0 and a fixed seed. Relying on seeding would poison the eval harness with apparent "regressions" that are really just sampling noise.

**Decision.** Cache LLM outputs keyed by SHA-256 of canonicalized `(provider, model, system, user, schema_name)`. Implementation lives in `packages/agents/src/agents/llm.py` (`prompt_cache_key`, `get_cached`, `set_cached`) backed by `diskcache` in `.cache/llm/`. Every `LLMClient.structured(...)` call checks the cache first, falls through to the provider on miss, validates the response into a Pydantic model, and writes the validated dict back.

**Consequences.** (+) True idempotency — reruns on unchanged prompts are free. (+) Shields against Gemini free-tier rate limits during iteration. (+) Cuts per-eval cost dramatically as prompts stabilize. (−) Cache invalidation is the user's responsibility: anything that should change the output (new prompt text, new model, new schema version) changes the cache key automatically, but silent prompt drift in string formatting will silently reuse old outputs. We accept this and document cache-clearing as `rm -rf .cache/llm` during prompt iteration. (−) Cache files can grow; gitignored and pruned on schedule.
