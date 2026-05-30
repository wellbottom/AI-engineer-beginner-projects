"""Deep Research FastAPI application (port 8004).

Wires the pure logic in :mod:`app.logic` / :mod:`app.schemas` into a FastAPI app:

- **Startup config validation** (Requirements 3.9, 3.13): ``load_settings`` is
  called with ``LLM_API_KEY``, ``TAVILY_API_KEY``, and ``HF_TOKEN`` plus the five
  ``DB_*`` variables required, so a misconfigured service aborts startup naming
  every missing variable instead of serving requests. Deep Research uses the LLM
  (decomposition + synthesis), Tavily (search), and HF embeddings + Chroma (vector
  store), so all three provider credentials are required here. The
  :class:`~ai_shared.errors.MissingConfigError` is allowed to propagate out of the
  lifespan so the process exits non-zero.
- **Lifespan** (design "Connection lifecycle"): builds the shared engine /
  ``HistoryRepository`` / ``LLMClient`` / ``TavilySearch`` / ``HFEmbeddings`` /
  ``ChromaVectorStore`` at startup and disposes the engine on shutdown
  (``ai_shared.db.dispose_engine``).
- **CORS** enabled for the frontend origin so the SPA can call the service.
- ``GET /health`` — liveness probe.
- ``POST /research`` — validates (Requirement 7.8) then streams the multi-step
  research over SSE (Requirements 7.1–7.6) and persists the completed report
  (Requirements 12.4, 12.8).
- ``GET /history`` / ``GET /history/{id}`` — browse persisted reports
  (Requirements 13.1, 13.3).

**SSE decision (BUG-004).** ``POST /research`` streams over SSE using FastAPI's
``StreamingResponse(media_type="text/event-stream")`` yielding the
``ai_shared.sse`` frame strings directly — ``sse-starlette`` is intentionally NOT
used (it would double-encode the already-formatted frames).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from ai_shared.config import Settings, load_settings
from ai_shared.db import dispose_engine, get_sessionmaker
from ai_shared.embeddings import HFEmbeddings
from ai_shared.errors import AISharedError, PersistenceError
from ai_shared.history import DeepResearchRecord, HistoryRepository, ProjectId
from ai_shared.llm_client import LLMClient
from ai_shared.search import TavilySearch
from ai_shared.vectorstore import ChromaVectorStore

from .logic import research_sse
from .schemas import validate_topic
from .serialize import record_to_json, summary_to_json

logger = logging.getLogger("deep_research")

#: Environment variables this service requires at startup. ``LLM_API_KEY`` is the
#: gateway credential, ``TAVILY_API_KEY`` the Search_Provider credential, and
#: ``HF_TOKEN`` the Embeddings_Service credential (deep research always uses LLM +
#: Tavily + HF embeddings + Chroma); the five ``DB_*`` variables back the
#: History_Store (Requirements 3.9, 3.13). ``LLM_BASE_URL``/``LLM_MODEL``/
#: ``EMBEDDING_MODEL``/``CHROMA_PATH`` have safe defaults.
REQUIRED_ENV = [
    "LLM_API_KEY",
    "TAVILY_API_KEY",
    "HF_TOKEN",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

#: Allowed CORS origins for the Shared_Frontend. Overridable via
#: ``DEEPRESEARCH_CORS_ORIGINS`` (comma-separated); defaults to the SPA dev server.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


def _cors_origins() -> list[str]:
    raw = os.environ.get("DEEPRESEARCH_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config, build shared resources at startup, dispose on shutdown.

    A missing required variable raises :class:`MissingConfigError` here (before any
    request is served), which propagates so the process exits non-zero naming the
    missing variables (Requirements 3.9, 3.13).
    """
    settings: Settings = load_settings(required=REQUIRED_ENV)
    app.state.settings = settings
    app.state.client = LLMClient(settings)
    app.state.search = TavilySearch(settings)
    app.state.embeddings = HFEmbeddings(settings)
    app.state.vector_store = ChromaVectorStore(settings)
    app.state.repository = HistoryRepository(get_sessionmaker(settings))
    logger.info(
        "Deep Research service started (model=%s, embedding_model=%s)",
        settings.llm_model,
        settings.embedding_model,
    )
    try:
        yield
    finally:
        # Dispose only this service's engine/pool on shutdown.
        dispose_engine(settings)
        logger.info("Deep Research service stopped; DB engine disposed")


app = FastAPI(title="Deep Research", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AISharedError)
async def _ai_shared_error_handler(_: Request, exc: AISharedError) -> JSONResponse:
    """Map a structured error to its HTTP status + shared JSON envelope."""
    status = exc.http_status or 500
    return JSONResponse(status_code=status, content=exc.to_dict())


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "deep-research"}


@app.post("/research")
async def research(request: Request):
    """Validate, then stream the multi-step research over SSE.

    On invalid input a :class:`ValidationError` is raised (handled into a 422)
    before the topic is decomposed or any search is performed (Requirement 7.8). On
    valid input the response is an SSE stream of ``progress`` frames terminated by a
    ``done`` (success, carrying the report + citations + persistence) or a terminal
    ``error`` (decomposition / search / embeddings / synthesis failure).
    """
    payload = await request.json()
    # Raises ValidationError (-> 422) before any decomposition/search (Requirement 7.8).
    topic = validate_topic(payload.get("topic"))

    return StreamingResponse(
        research_sse(
            topic,
            client=app.state.client,
            search=app.state.search,
            embeddings=app.state.embeddings,
            vector_store=app.state.vector_store,
            repository=app.state.repository,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history")
async def list_history():
    """Return newest-first summaries of persisted reports (Requirement 13.3).

    A retrieval failure maps to a 502 identifying the history-retrieval failure
    (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        summaries = repository.list_records(ProjectId.DEEP_RESEARCH)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())
    return [summary_to_json(s) for s in summaries]


@app.get("/history/{record_id}")
async def get_history(record_id: int):
    """Return the full persisted report for ``record_id`` (Requirement 13.3).

    Unknown id -> 404; a retrieval failure -> 502 identifying the history-retrieval
    failure (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        record = repository.get_record(ProjectId.DEEP_RESEARCH, record_id)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())

    if record is None or not isinstance(record, DeepResearchRecord):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "action": "retrieve history",
                    "reason": f"No deep-research history record with id {record_id}",
                    "details": {"id": record_id},
                }
            },
        )
    return record_to_json(str(record_id), record)
