"""Customer Support Chatbot FastAPI application (port 8002).

Wires the pure logic in :mod:`app.logic` / :mod:`app.schemas` /
:mod:`app.session_store` into a FastAPI app:

- **Startup config validation** (Requirements 3.9, 3.13): ``load_settings`` is
  called with ``LLM_API_KEY`` plus the five ``DB_*`` variables required, so a
  misconfigured service aborts startup naming every missing variable instead of
  serving requests. :class:`~ai_shared.errors.MissingConfigError` propagates out of
  the lifespan so the process exits non-zero.
- **System prompt** (Requirement 5.3): the configurable persona/topics system
  prompt is loaded **once** at startup (``load_system_prompt``) and held on
  ``app.state`` for the process lifetime — never re-read per request.
- **Lifespan** (design "Connection lifecycle"): builds the shared engine /
  ``HistoryRepository`` / ``LLMClient`` / in-memory ``SessionStore`` / classifier
  at startup and disposes the engine on shutdown.
- **CORS** enabled for the frontend origin so the SPA can call the service.
- ``GET /health`` — liveness probe.
- ``POST /session`` / ``DELETE /session/{id}`` — create/discard an in-memory
  session (Requirement 5.1).
- ``POST /chat`` — validate (Requirement 5.7) then stream the reply over SSE
  (Requirements 5.2, 5.4, 5.5, 5.6) and persist the completed turn
  (Requirements 12.4, 12.6).
- ``GET /history`` / ``GET /history/{id}`` — browse persisted sessions/turns
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
from ai_shared.history import HistoryRepository, ProjectId
from ai_shared.llm_client import LLMClient

from .classifier import load_classifier
from .history_read import get_session_detail
from .logic import chat_sse
from .schemas import validate_message
from .serialize import session_detail_to_json, summary_to_json
from .session_store import SessionStore
from .system_prompt import load_system_prompt

logger = logging.getLogger("support_chatbot")

#: Environment variables this service requires at startup. ``LLM_API_KEY`` is the
#: gateway credential; the five ``DB_*`` variables back the History_Store
#: (Requirements 3.9, 3.13). ``LLM_BASE_URL``/``LLM_MODEL`` have safe defaults, and
#: the system-prompt/classifier env vars are optional overrides.
REQUIRED_ENV = [
    "LLM_API_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

#: Allowed CORS origins for the Shared_Frontend. Overridable via
#: ``SUPPORT_CORS_ORIGINS`` (comma-separated); defaults to the SPA dev server.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


def _cors_origins() -> list[str]:
    raw = os.environ.get("SUPPORT_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config + load the system prompt at startup; dispose on shutdown.

    A missing required variable raises :class:`MissingConfigError` here (before any
    request is served), which propagates so the process exits non-zero naming the
    missing variables (Requirement 3.9). The configurable system prompt is loaded
    exactly once (Requirement 5.3) and held on ``app.state``.
    """
    settings: Settings = load_settings(required=REQUIRED_ENV)
    app.state.settings = settings
    app.state.client = LLMClient(settings)
    app.state.session_factory = get_sessionmaker(settings)
    app.state.repository = HistoryRepository(app.state.session_factory)
    app.state.store = SessionStore()
    # Requirement 5.3 — load the configurable persona/topics prompt ONCE.
    app.state.system_prompt = load_system_prompt()
    app.state.classifier = load_classifier()
    logger.info(
        "Support Chatbot service started (model=%s, system_prompt_chars=%d)",
        settings.llm_model,
        len(app.state.system_prompt),
    )
    try:
        yield
    finally:
        dispose_engine(settings)
        logger.info("Support Chatbot service stopped; DB engine disposed")


app = FastAPI(title="Support Chatbot", version="0.1.0", lifespan=lifespan)

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
    return {"status": "ok", "service": "support-chatbot"}


@app.post("/session")
async def create_session() -> dict[str, str]:
    """Create a new in-memory chat session and return its id (Requirement 5.1)."""
    store: SessionStore = app.state.store
    session_id = store.create()
    return {"session_id": session_id}


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, object]:
    """Discard an in-memory session (Requirement 5.1).

    The durable History_Records are unaffected (Requirement 12.6); ``deleted``
    reports whether an active session was present.
    """
    store: SessionStore = app.state.store
    deleted = store.delete(session_id)
    return {"session_id": session_id, "deleted": deleted}


@app.post("/chat")
async def chat(request: Request):
    """Validate, stream the reply over SSE, and persist the completed turn.

    On invalid input a :class:`ValidationError` is raised (handled into a 422)
    before the LLM_Client is contacted (Requirement 5.7). On valid input the
    response is an SSE stream of ``data`` frames terminated by ``done`` (success,
    incl. the out-of-scope canned reply) or a terminal ``error`` (temporarily
    unavailable) on a gateway refusal/timeout.
    """
    payload = await request.json()
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        # session_id is required to scope the in-memory + durable conversation.
        from ai_shared.errors import ValidationError

        raise ValidationError(
            field="session_id",
            constraint="must be a non-empty string",
            action="chat",
        )

    # Raises ValidationError (-> 422) before any gateway call (Requirement 5.7).
    message = validate_message(payload.get("message"))

    return StreamingResponse(
        chat_sse(
            session_id,
            message,
            store=app.state.store,
            client=app.state.client,
            repository=app.state.repository,
            system_prompt=app.state.system_prompt,
            classifier=app.state.classifier,
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
    """Return newest-first summaries of persisted chat sessions (Requirement 13.3).

    A retrieval failure maps to a 502 identifying the history-retrieval failure
    (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        summaries = repository.list_records(ProjectId.SUPPORT)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())
    return [summary_to_json(s) for s in summaries]


@app.get("/history/{session_pk}")
async def get_history(session_pk: int):
    """Return one persisted session's full ordered turns (Requirements 12.6, 13.3).

    Unknown id -> 404; a retrieval failure -> 502 identifying the history-retrieval
    failure (Requirement 13.6). Uses the service-layer reader (BUG-005) to surface
    the whole conversation, not just the latest turn.
    """
    session_factory = app.state.session_factory
    try:
        detail = get_session_detail(session_factory, session_pk)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())

    if detail is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "action": "retrieve history",
                    "reason": f"No chat session history record with id {session_pk}",
                    "details": {"id": session_pk},
                }
            },
        )
    return session_detail_to_json(detail)
