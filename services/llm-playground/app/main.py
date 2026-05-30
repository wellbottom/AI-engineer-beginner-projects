"""LLM Playground FastAPI application (port 8001).

Wires the pure logic in :mod:`app.logic` / :mod:`app.schemas` into a FastAPI app:

- **Startup config validation** (Requirements 3.9, 3.13): ``load_settings`` is
  called with ``LLM_API_KEY`` plus the five ``DB_*`` variables required, so a
  misconfigured service aborts startup naming every missing variable instead of
  serving requests. The :class:`~ai_shared.errors.MissingConfigError` is allowed to
  propagate out of the lifespan so the process exits non-zero.
- **Lifespan** (design "Connection lifecycle"): builds the shared engine /
  ``HistoryRepository`` at startup and disposes the engine on shutdown
  (``ai_shared.db.dispose_engine``).
- **CORS** enabled for the frontend origin so the SPA can call the service.
- ``GET /health`` — liveness probe.
- ``POST /generate`` — validates (Requirement 4.7) then streams over SSE
  (Requirements 4.3-4.6) and persists the completed run (Requirements 12.3-12.5).
- ``GET /history`` / ``GET /history/{id}`` — browse persisted runs
  (Requirements 13.1, 13.3).
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
from ai_shared.errors import AISharedError, PersistenceError
from ai_shared.history import HistoryRepository, PlaygroundRecord, ProjectId
from ai_shared.llm_client import LLMClient

from .logic import generate_sse
from .schemas import validate_playground_request
from .serialize import record_to_json, summary_to_json

logger = logging.getLogger("llm_playground")

#: Environment variables this service requires at startup. ``LLM_API_KEY`` is the
#: gateway credential; the five ``DB_*`` variables back the History_Store
#: (Requirements 3.9, 3.13). ``LLM_BASE_URL``/``LLM_MODEL`` have safe defaults.
REQUIRED_ENV = [
    "LLM_API_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

#: Allowed CORS origins for the Shared_Frontend. Overridable via
#: ``PLAYGROUND_CORS_ORIGINS`` (comma-separated); defaults to the SPA dev server.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


def _cors_origins() -> list[str]:
    raw = os.environ.get("PLAYGROUND_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config, build shared resources at startup, dispose on shutdown.

    A missing required variable raises :class:`MissingConfigError` here (before any
    request is served), which propagates so the process exits non-zero naming the
    missing variables (Requirement 3.9).
    """
    settings: Settings = load_settings(required=REQUIRED_ENV)
    app.state.settings = settings
    app.state.client = LLMClient(settings)
    app.state.repository = HistoryRepository(get_sessionmaker(settings))
    logger.info("LLM Playground service started (model=%s)", settings.llm_model)
    try:
        yield
    finally:
        # Dispose only this service's engine/pool on shutdown.
        dispose_engine(settings)
        logger.info("LLM Playground service stopped; DB engine disposed")


app = FastAPI(title="LLM Playground", version="0.1.0", lifespan=lifespan)

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
    return {"status": "ok", "service": "llm-playground"}


@app.post("/generate")
async def generate(request: Request):
    """Validate, stream the generation over SSE, and persist on completion.

    On invalid input a :class:`ValidationError` is raised (handled into a 422)
    before the LLM_Client is contacted (Requirement 4.7). On valid input the
    response is an SSE stream of ``data`` frames terminated by ``done`` (or a
    terminal ``error`` on a gateway failure).
    """
    payload = await request.json()
    # Raises ValidationError (-> 422) before any gateway call (Requirement 4.7).
    validated = validate_playground_request(payload)

    settings: Settings = app.state.settings
    client: LLMClient = app.state.client
    repository: HistoryRepository = app.state.repository

    return StreamingResponse(
        generate_sse(
            validated,
            client,
            repository,
            default_model=settings.llm_model,
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
    """Return newest-first summaries of persisted playground runs (Requirement 13.3).

    A retrieval failure maps to a 502 identifying the history-retrieval failure
    (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        summaries = repository.list_records(ProjectId.PLAYGROUND)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())
    return [summary_to_json(s) for s in summaries]


@app.get("/history/{record_id}")
async def get_history(record_id: int):
    """Return the full persisted run for ``record_id`` (Requirement 13.3).

    Unknown id -> 404; a retrieval failure -> 502 identifying the history-retrieval
    failure (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        record = repository.get_record(ProjectId.PLAYGROUND, record_id)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())

    if record is None or not isinstance(record, PlaygroundRecord):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "action": "retrieve history",
                    "reason": f"No playground history record with id {record_id}",
                    "details": {"id": record_id},
                }
            },
        )
    return record_to_json(str(record_id), record)
