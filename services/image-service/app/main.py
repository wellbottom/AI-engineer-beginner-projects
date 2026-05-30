"""Image Generation FastAPI application (port 8005).

Wires the pure logic in :mod:`app.logic` / :mod:`app.schemas` / :mod:`app.codec`
and the provider wrapper :mod:`app.provider` into a FastAPI app:

- **Startup config validation** (Requirements 3.9, 3.13): ``load_settings`` is
  called with ``HF_TOKEN`` (the Image_Provider credential) plus the five ``DB_*``
  variables required, so a misconfigured service aborts startup naming every
  missing variable instead of serving requests. The
  :class:`~ai_shared.errors.MissingConfigError` is allowed to propagate out of the
  lifespan so the process exits non-zero. (Image generation uses only HF +
  the Database — no LLM gateway / Tavily — so ``LLM_API_KEY``/``TAVILY_API_KEY``
  are NOT required here.)
- **Lifespan** (design "Connection lifecycle"): builds the shared engine /
  ``HistoryRepository`` and the :class:`~app.provider.HFImageProvider` at startup
  and disposes the engine on shutdown (``ai_shared.db.dispose_engine``).
- **CORS** enabled for the frontend origin so the SPA can call the service.
- ``GET /health`` — liveness probe.
- ``GET /models`` — the selectable model identifiers, default first (Requirement 8.3).
- ``POST /generate`` — **non-streamed**: validates (Requirement 8.6), resolves the
  model (Requirement 8.3), calls the provider with a 60s timeout (Requirement 8.7),
  and returns a JSON body with the web-renderable image (Requirement 8.2) +
  persistence indication (Requirements 12.4, 12.9). A provider error / timeout maps
  to the shared error envelope with the provider reason and no image data
  (Requirements 8.5, 8.7).
- ``GET /history`` / ``GET /history/{id}`` — browse persisted generations; the
  detail view re-emits the stored PNG (Requirements 13.1, 13.3).

**Non-streamed decision.** Unlike the SSE services, ``POST /generate`` returns a
single ``application/json`` body (the image is a complete artifact, not a token
stream), so the persistence-failure indication is carried in the body as
``persistence: {ok, operation_id?}`` (Requirement 12.4), not on an SSE ``done``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ai_shared.config import Settings, load_settings
from ai_shared.db import dispose_engine, get_sessionmaker
from ai_shared.errors import AISharedError, PersistenceError
from ai_shared.history import HistoryRepository, ImageRecord, ProjectId

from .logic import generate_image
from .provider import HFImageProvider
from .schemas import SELECTABLE_MODELS, validate_image_request
from .serialize import record_to_json, summary_to_json

logger = logging.getLogger("image_service")

#: Environment variables this service requires at startup. ``HF_TOKEN`` is the
#: Image_Provider (Hugging Face) credential; the five ``DB_*`` variables back the
#: History_Store (Requirements 3.9, 3.13). The image service does NOT use the LLM
#: gateway or Tavily, so those credentials are not required. ``HF_TOKEN`` has no
#: safe default, so it must be present.
REQUIRED_ENV = [
    "HF_TOKEN",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

#: Allowed CORS origins for the Shared_Frontend. Overridable via
#: ``IMAGE_CORS_ORIGINS`` (comma-separated); defaults to the SPA dev server.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


def _cors_origins() -> list[str]:
    raw = os.environ.get("IMAGE_CORS_ORIGINS", "").strip()
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
    app.state.provider = HFImageProvider(settings)
    app.state.repository = HistoryRepository(get_sessionmaker(settings))
    logger.info("Image Generation service started")
    try:
        yield
    finally:
        # Dispose only this service's engine/pool on shutdown.
        dispose_engine(settings)
        logger.info("Image Generation service stopped; DB engine disposed")


app = FastAPI(title="Image Generation", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AISharedError)
async def _ai_shared_error_handler(_: Request, exc: AISharedError) -> JSONResponse:
    """Map a structured error to its HTTP status + shared JSON envelope.

    A provider error -> 502, a timeout -> 504, validation -> 422; each body is the
    shared ``{"error": {...}}`` envelope and carries **no image data**
    (Requirements 8.5, 8.7).
    """
    status = exc.http_status or 500
    return JSONResponse(status_code=status, content=exc.to_dict())


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "image-service"}


@app.get("/models")
async def list_models() -> list[str]:
    """Return the selectable model identifiers, default first (Requirement 8.3)."""
    return list(SELECTABLE_MODELS)


@app.post("/generate")
async def generate(request: Request):
    """Validate, generate (non-streamed), persist, and return the JSON body.

    On invalid input a :class:`ValidationError` is raised (handled into a 422)
    before the Image_Provider is contacted (Requirement 8.6). On valid input the
    image is generated with a 60s timeout; the response is a JSON body with the
    web-renderable image (Requirement 8.2) and the persistence indication
    (Requirements 12.4, 12.9). A provider error / timeout is raised as a structured
    error and handled into an error response with the provider reason and no image
    data (Requirements 8.5, 8.7).
    """
    payload = await request.json()
    # Raises ValidationError (-> 422) before any provider call (Requirement 8.6).
    validated = validate_image_request(payload)

    provider: HFImageProvider = app.state.provider
    repository: HistoryRepository = app.state.repository

    # A provider error / timeout propagates to the AISharedError handler (502/504)
    # with the provider reason and no image data (Requirements 8.5, 8.7).
    body = await generate_image(validated, provider=provider, repository=repository)
    return JSONResponse(status_code=200, content=body)


@app.get("/history")
async def list_history():
    """Return newest-first summaries of persisted generations (Requirement 13.3).

    A retrieval failure maps to a 502 identifying the history-retrieval failure
    (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        summaries = repository.list_records(ProjectId.IMAGE)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())
    return [summary_to_json(s) for s in summaries]


@app.get("/history/{record_id}")
async def get_history(record_id: int):
    """Return the full persisted generation for ``record_id`` (Requirement 13.3).

    Re-emits the stored PNG as a web-renderable payload (Requirement 12.9). Unknown
    id -> 404; a retrieval failure -> 502 identifying the history-retrieval failure
    (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        record = repository.get_record(ProjectId.IMAGE, record_id)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())

    if record is None or not isinstance(record, ImageRecord):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "action": "retrieve history",
                    "reason": f"No image history record with id {record_id}",
                    "details": {"id": record_id},
                }
            },
        )
    return record_to_json(str(record_id), record)
