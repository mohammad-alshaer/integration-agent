"""Smoke test: structured-output call to Gemini 2.5 Pro + Langfuse v4 trace.

This verifies the Day 4 stack end-to-end:
  - google-genai client reads GEMINI_API_KEY from .env
  - Pydantic response_schema enforces a strict output shape
  - Langfuse @observe decorator captures the function as a trace
    (visible in the Langfuse dashboard within ~10 seconds)

Run:  ./.venv/Scripts/python.exe scripts/hello_gemini.py
"""

from __future__ import annotations

# Corporate TLS proxy: Dar inserts its own CA for HTTPS inspection. Python's
# default cert bundle (certifi) doesn't trust it; the Windows cert store does.
# truststore routes ssl/urllib3/httpx/requests through the Windows store.
# MUST run before any HTTPS client is constructed.
import truststore

truststore.inject_into_ssl()

import contextlib  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

from dotenv import load_dotenv  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from langfuse import get_client, observe  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

load_dotenv()


class Greeting(BaseModel):
    """Structured output schema for the smoke test."""

    language: str = Field(description="ISO 639-1 language code, e.g. 'fr'")
    message: str = Field(description="A short friendly greeting in that language")
    confidence: float = Field(ge=0.0, le=1.0, description="Self-judged confidence 0-1")


@observe(name="hello_gemini")
def greet_in_french() -> Greeting:
    api_key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")

    client = genai.Client(api_key=api_key)
    prompt = "Greet me in French. Keep it short and warm."

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Greeting,
            temperature=0.2,
        ),
    )
    result: Greeting = response.parsed
    # @observe auto-captures function args + return value + timing into the trace.
    # In Langfuse v4 OTel-based, explicit enrichment uses a different API than v3;
    # for the M0 smoke test the auto-capture is sufficient. We'll add richer
    # generation-level metadata in packages/agents/src/agents/llm.py at M1.
    return result


def main() -> int:
    try:
        greeting = greet_in_french()
    except RuntimeError as exc:
        print(f"[hello_gemini] setup error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[hello_gemini] call failed: {exc}", file=sys.stderr)
        return 1

    print(greeting.model_dump_json(indent=2))

    # Flush Langfuse events before exit (important for short-lived scripts)
    with contextlib.suppress(Exception):
        get_client().flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
