"""Long-lived dependencies built once at startup, exposed via FastAPI Depends."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import HTTPException, Request

from agents.embeddings import Embedder
from agents.llm import LLMClient
from agents.vector_store import SourceVectorStore
from api.config import Settings


@dataclass
class ApiDeps:
    settings: Settings
    llm: LLMClient
    embedder: Embedder
    store: SourceVectorStore
    map_lock: asyncio.Lock


def get_deps(request: Request) -> ApiDeps:
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(
            status_code=503,
            detail="API deps not initialized — check startup logs (likely missing GEMINI_API_KEY).",
        )
    return deps
