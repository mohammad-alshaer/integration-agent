"""Smoke test: structured-output call to Gemini 2.5 Pro + Langfuse v4 trace.

This verifies the Day 4 stack end-to-end:
  - google-genai client reads GEMINI_API_KEY from .env
  - Pydantic response_schema enforces a strict output shape
  - Langfuse @observe decorator captures the function as a trace
    (visible in the Langfuse dashboard within ~10 seconds)

Run:  ./.venv/Scripts/python.exe scripts/hello_gemini.py
"""

from __future__ import annotations

import contextlib
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from langfuse import get_client, observe
from pydantic import BaseModel, Field

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

    # Enrich the active Langfuse span (best-effort — v4 OTel-based API)
    try:
        lf = get_client()
        usage = response.usage_metadata
        lf.update_current_trace(
            input={"prompt": prompt},
            output=result.model_dump(),
            metadata={
                "model": model,
                "tokens_in": getattr(usage, "prompt_token_count", 0),
                "tokens_out": getattr(usage, "candidates_token_count", 0),
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[hello_gemini] langfuse enrichment failed (non-fatal): {exc}", file=sys.stderr)

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
