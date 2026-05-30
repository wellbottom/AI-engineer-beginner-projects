"""Capstone FastAPI application (port 8006) — Agent + RAG + MCP.

Wires the framework-agnostic logic in :mod:`app.agent` / :mod:`app.ingest` /
:mod:`app.schemas` / :mod:`app.mcp` into a FastAPI app:

- **Startup config validation** (Requirements 3.9, 3.13): ``load_settings`` is called
  with ``LLM_API_KEY`` (the gateway credential used by the Agent's answer synthesis)
  and ``HF_TOKEN`` (the Embeddings_Service credential used by RAG) plus the five
  ``DB_*`` variables required, so a misconfigured service aborts startup naming every
  missing variable instead of serving requests. The capstone uses the LLM + HF
  embeddings + Chroma, so both provider credentials are required here (Tavily is not
  used). :class:`~ai_shared.errors.MissingConfigError` propagates out of the lifespan
  so the process exits non-zero.
- **Lifespan** (design "Connection lifecycle"): builds the shared engine /
  ``HistoryRepository`` / ``LLMClient`` / ``HFEmbeddings`` / ``ChromaVectorStore`` and
  the in-process ``MCPServer`` at startup, and disposes the engine on shutdown
  (``ai_shared.db.dispose_engine``).
- **CORS** enabled for the frontend origin so the SPA can call the service.
- ``GET /health`` — liveness probe.
- ``GET /tools`` — the MCP tools exposed to the Agent (Requirement 9.2 discovery).
- ``POST /documents`` — **non-streamed**: ingest uploads (≤10 MB each), store
  embeddings, return a confirmation naming exactly the ingested documents + the
  persistence indication (Requirements 9.5, 9.10, 12.11, 12.4).
- ``POST /task`` — validate (Requirement 9.9) then stream the Agent run over SSE
  (Requirements 9.4, 9.6, 9.7, 9.8, 9.11) and persist the task run (Requirements
  12.10, 12.4).
- ``GET /history`` / ``GET /history/{id}`` — browse persisted task runs + ingestions
  (Requirements 13.1, 13.3); the detail id is the ``kind``-discriminated string id
  (BUG-003).

**SSE decision (BUG-004).** ``POST /task`` streams over SSE using FastAPI's
``StreamingResponse(media_type="text/event-stream")`` yielding the ``ai_shared.sse``
frame strings directly — ``sse-starlette`` is intentionally NOT used.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from ai_shared.config import Settings, load_settings
from ai_shared.db import dispose_engine, get_sessionmaker
from ai_shared.embeddings import HFEmbeddings
from ai_shared.errors import AISharedError, PersistenceError, ValidationError
from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneTaskRecord,
    HistoryRepository,
    ProjectId,
)
from ai_shared.llm_client import LLMClient
from ai_shared.vectorstore import ChromaVectorStore

from .agent import make_rag_retriever, run_task_sse
from .ingest import DocumentUpload, ingest_and_persist, validate_upload_size
from .mcp import build_default_mcp_server
from .schemas import validate_task
from .serialize import record_to_json, summary_to_json

logger = logging.getLogger("capstone")

#: Environment variables this service requires at startup. ``LLM_API_KEY`` is the
#: gateway credential (the Agent synthesizes answers via the LLM) and ``HF_TOKEN`` is
#: the Embeddings_Service credential (RAG retrieval + document ingestion embed via
#: HF, then store in Chroma); the five ``DB_*`` variables back the History_Store
#: (Requirements 3.9, 3.13). The capstone does NOT use Tavily, so ``TAVILY_API_KEY``
#: is not required. ``LLM_BASE_URL``/``LLM_MODEL``/``EMBEDDING_MODEL``/``CHROMA_PATH``
#: have safe defaults.
REQUIRED_ENV = [
    "LLM_API_KEY",
    "HF_TOKEN",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

#: The Chroma collection holding the capstone's ingested document embeddings. A
#: single shared collection so ingested documents are retrievable by later task runs.
CAPSTONE_COLLECTION = "capstone-documents"

#: Allowed CORS origins for the Shared_Frontend. Overridable via
#: ``CAPSTONE_CORS_ORIGINS`` (comma-separated); defaults to the SPA dev server.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


def _cors_origins() -> list[str]:
    raw = os.environ.get("CAPSTONE_CORS_ORIGINS", "").strip()
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
    app.state.embeddings = HFEmbeddings(settings)
    app.state.vector_store = ChromaVectorStore(settings)
    app.state.mcp_server = build_default_mcp_server()
    app.state.repository = HistoryRepository(get_sessionmaker(settings))
    app.state.collection = CAPSTONE_COLLECTION
    logger.info(
        "Capstone service started (model=%s, embedding_model=%s, tools=%s)",
        settings.llm_model,
        settings.embedding_model,
        app.state.mcp_server.tool_names(),
    )
    try:
        yield
    finally:
        dispose_engine(settings)
        logger.info("Capstone service stopped; DB engine disposed")


app = FastAPI(title="Capstone", version="0.1.0", lifespan=lifespan)

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
    return {"status": "ok", "service": "capstone"}


@app.get("/tools")
async def list_tools() -> list[dict[str, str]]:
    """Return the MCP tools exposed to the Agent (Requirement 9.2 discovery)."""
    return [spec.to_json() for spec in app.state.mcp_server.list_tools()]


@app.post("/documents")
async def ingest(documents: list[UploadFile] = File(...)):
    """Ingest uploaded documents (non-streamed) and return the confirmation body.

    Each upload is validated against the ≤10 MB bound (Requirement 9.5) before the
    Embeddings_Service is contacted; an oversized document yields a 422 naming it. On
    success the documents are embedded + stored in Chroma and the JSON body names
    exactly the ingested documents (Property 25) plus the persistence indication
    (Requirements 12.11, 12.4). An embeddings failure maps to a 502 identifying the
    ingestion failure (Requirement 9.10).
    """
    uploads: list[DocumentUpload] = []
    for upload in documents:
        data = await upload.read()
        name = upload.filename or "document"
        # Reject oversized documents before any provider call (Requirement 9.5).
        validate_upload_size(name, len(data))
        uploads.append(DocumentUpload(name=name, data=data))

    if not uploads:
        raise ValidationError(
            field="documents",
            constraint="at least one document is required",
            action="ingest documents",
        )

    # An embeddings/vector-store failure propagates to the AISharedError handler
    # (502) identifying the ingestion failure (Requirement 9.10). Nothing persisted.
    body = ingest_and_persist(
        uploads,
        embeddings=app.state.embeddings,
        vector_store=app.state.vector_store,
        repository=app.state.repository,
        collection=app.state.collection,
    )
    return JSONResponse(status_code=200, content=body)


@app.post("/task")
async def run_task(request: Request):
    """Validate, then stream the Agent run over SSE and persist on completion.

    On invalid input a :class:`ValidationError` is raised (handled into a 422) before
    the Agent is started (Requirement 9.9). On valid input the response is an SSE
    stream of ``progress`` step updates (phase + sequence position, Requirement 9.7)
    terminated by a ``done`` carrying the final answer + invoked tools + referenced
    sources + step-limit indication + persistence (Requirements 9.6, 9.11, 12.10), or
    a terminal ``error`` (retrieval / synthesis failure).
    """
    payload = await request.json()
    # Raises ValidationError (-> 422) before the Agent is started (Requirement 9.9).
    task = validate_task(payload.get("task"))

    retriever = make_rag_retriever(
        embeddings=app.state.embeddings,
        vector_store=app.state.vector_store,
        collection=app.state.collection,
    )

    return StreamingResponse(
        run_task_sse(
            task,
            mcp_server=app.state.mcp_server,
            retriever=retriever,
            repository=app.state.repository,
            client=app.state.client,
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
    """Return newest-first merged summaries of task runs + ingestions (Req 13.3).

    Each summary carries the ``kind``-discriminated string id (``"task:<n>"`` /
    ``"ingest:<n>"``, BUG-003). A retrieval failure maps to a 502 identifying the
    history-retrieval failure (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        summaries = repository.list_records(ProjectId.CAPSTONE)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())
    return [summary_to_json(s) for s in summaries]


@app.get("/history/{record_id}")
async def get_history(record_id: str):
    """Return the full persisted capstone record for ``record_id`` (Requirement 13.3).

    ``record_id`` is the ``kind``-discriminated **string** id (``"task:<n>"`` /
    ``"ingest:<n>"``) from ``GET /history`` — never a bare int (BUG-003). The shared
    repository selects the correct table by the id's discriminator. Unknown or
    malformed ids -> 404; a retrieval failure -> 502 identifying the history-retrieval
    failure (Requirement 13.6).
    """
    repository: HistoryRepository = app.state.repository
    try:
        record = repository.get_record(ProjectId.CAPSTONE, record_id)
    except PersistenceError as exc:
        return JSONResponse(status_code=exc.http_status or 502, content=exc.to_dict())

    if record is None or not isinstance(record, (CapstoneTaskRecord, CapstoneIngestRecord)):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "action": "retrieve history",
                    "reason": f"No capstone history record with id {record_id!r}",
                    "details": {"id": record_id},
                }
            },
        )
    return record_to_json(record_id, record)
