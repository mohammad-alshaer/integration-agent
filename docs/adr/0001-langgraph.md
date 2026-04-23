# ADR 0001 — Use LangGraph for multi-agent orchestration

**Status:** Accepted (2026-04-23)

**Context.** Integration-Agent is a multi-specialist pipeline: Coordinator → Schema Explorer → Semantic Matcher → Pattern Classifier → Transformation Generator → Validator → (retry loop). We need stateful graph orchestration with conditional routing, checkpointing, and a "replay" story for the UI's decision-playback timeline.

**Decision.** Use LangGraph (pinned `>=0.2,<0.3`). Its stateful graph + checkpointer model fits the shape of our pipeline natively; built-in persistence (SqliteSaver / PostgresSaver) gives us ~80% of the decision-playback requirement for free. Considered alternatives: hand-rolled state machine (reinventing checkpointing = 2-3 wks of wasted work), Anthropic Agent SDK (single-agent tool-loop, not a multi-specialist graph), OpenAI Agents SDK (not provider-native to our chosen LLM).

**Consequences.** Pin exact version in `pyproject.toml`; bump only on a feature branch with the eval harness green. If LangGraph ever becomes a drag, the specialists themselves stay portable because every specialist call goes through `LLMClient` and receives/emits Pydantic messages defined in `packages/schemas/`.
