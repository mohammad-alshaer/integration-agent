"""FastAPI app factory + lifespan.

truststore.inject_into_ssl() runs FIRST, before any module that constructs an
HTTPS client. The lifespan tolerates missing API keys so tests can override
deps via app.dependency_overrides without setting GEMINI_API_KEY.
"""

# Corporate TLS proxy: route Python TLS through Windows cert store.
# Must happen before any HTTPS client is constructed (LLMClient, embedder, Langfuse).
import truststore

truststore.inject_into_ssl()

import asyncio  # noqa: E402
import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from agents.embeddings import default_embedder  # noqa: E402
from agents.llm import GeminiProvider  # noqa: E402
from agents.vector_store import SourceVectorStore  # noqa: E402
from api.config import Settings  # noqa: E402
from api.deps import ApiDeps  # noqa: E402
from api.routers import eval as eval_router  # noqa: E402
from api.routers import health, map  # noqa: E402

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    settings = Settings()
    try:
        embedder = default_embedder()
        llm = GeminiProvider()
        store = SourceVectorStore(settings.vector_db_path, embedder)
        app.state.deps = ApiDeps(
            settings=settings,
            llm=llm,
            embedder=embedder,
            store=store,
            map_lock=asyncio.Lock(),
        )
        log.info(
            "api lifespan: deps ready (llm=%s/%s, embedder=%s/%s)",
            llm.provider,
            llm.model,
            getattr(embedder, "provider", "?"),
            embedder.model,
        )
    except Exception as e:  # noqa: BLE001 — log + run degraded so tests with overrides still work
        log.warning("api lifespan: deps init failed (%s); /health and /map will 503", e)
        app.state.deps = None
    try:
        yield
    finally:
        deps = getattr(app.state, "deps", None)
        if deps is not None:
            deps.store.close()


def create_app(*, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Integration-Agent API", version="0.1.0", lifespan=lifespan)
    cors_origin = (settings or Settings()).cors_origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cors_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(map.router)
    app.include_router(eval_router.router)
    return app


app = create_app()
