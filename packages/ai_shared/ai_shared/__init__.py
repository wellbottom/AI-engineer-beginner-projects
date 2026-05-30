"""``ai_shared`` — cross-cutting backend layer for the AI Engineer Practice Monorepo.

This package is installed as a local (editable) path dependency into each Python
service's own virtualenv, so every backend shares one configuration loader, one
structured error hierarchy, and (in later tasks) one LLM client, SSE helpers, and
persistence layer.

Task 2 delivers the configuration + error layer:

- :mod:`ai_shared.config` — :class:`~ai_shared.config.Settings` and
  :func:`~ai_shared.config.load_settings` (root ``.env`` loading + required-var
  validation, including the ``DB_*`` Database variables).
- :mod:`ai_shared.errors` — the structured error hierarchy with HTTP-status
  mapping and a shared ``{"error": {...}}`` JSON envelope.

Task 3 adds the LLM client and SSE helpers:

- :mod:`ai_shared.llm_types` — shared :class:`~ai_shared.llm_types.Message`,
  :class:`~ai_shared.llm_types.Usage`, :class:`~ai_shared.llm_types.Completion`,
  and :class:`~ai_shared.llm_types.StreamEvent` data models (Requirement 3.10).
- :mod:`ai_shared.llm_client` — :class:`~ai_shared.llm_client.LLMClient` wrapping
  the OpenAI-compatible gateway plus the pure
  :func:`~ai_shared.llm_client.resolve_model` (Requirements 3.3–3.8).
- :mod:`ai_shared.sse` — pure ``text/event-stream`` formatting helpers
  (Requirement 3.10).

Task 4 adds the shared persistence layer (Requirement 12):

- :mod:`ai_shared.models` — SQLAlchemy 2.x ORM tables for every project's
  History_Record (Requirements 12.2, 12.5–12.11).
- :mod:`ai_shared.db` — cached engine / ``sessionmaker`` / ``session_scope`` /
  ``dispose_engine`` lifecycle (Requirements 3.13, 12.3).
- :mod:`ai_shared.history` — the :class:`~ai_shared.history.ProjectId` enum, the
  ``HistoryRecord`` tagged union, the pure
  :func:`~ai_shared.history.build_history_record`, and the
  :class:`~ai_shared.history.HistoryRepository` (Requirements 12.1, 13.3).
- :mod:`ai_shared.persistence` — the best-effort persistence wrapper that applies
  the Requirement 12.4 policy (return the result, log + flag on failure).

Task 5 adds the provider wrappers (Requirements 6.1, 6.6, 7.2, 7.3, 7.7):

- :mod:`ai_shared.search` — :class:`~ai_shared.search.TavilySearch` web-search
  wrapper returning normalized, ranked :class:`~ai_shared.search.WebResult`
  objects (capped, per-call timeout, :class:`~ai_shared.errors.SearchError`).
- :mod:`ai_shared.embeddings` — :class:`~ai_shared.embeddings.HFEmbeddings`
  Hugging Face embeddings wrapper (:class:`~ai_shared.errors.EmbeddingsError`).
- :mod:`ai_shared.vectorstore` — :class:`~ai_shared.vectorstore.ChromaVectorStore`
  local persistent Chroma wrapper (add / top-k query).

Each isolates its third-party SDK (``tavily`` / ``huggingface_hub`` / ``chromadb``)
behind a lazy import and accepts an injected client, so the normalization,
capping, timeout, and error-mapping logic stays unit-testable without the heavy
dependency installed.
"""

from __future__ import annotations

from . import (
    config,
    db,
    embeddings,
    errors,
    history,
    llm_client,
    llm_types,
    models,
    persistence,
    search,
    sse,
    vectorstore,
)
from .config import Settings, load_settings
from .db import (
    dispose_engine,
    get_engine,
    get_sessionmaker,
    session_scope,
)
from .errors import (
    AISharedError,
    EmbeddingsError,
    ImageProviderError,
    ImageTimeoutError,
    LLMGatewayError,
    LLMTimeoutError,
    MissingConfigError,
    PersistenceError,
    SearchError,
    ValidationError,
)
from .history import (
    CapstoneIngestRecord,
    CapstoneIngestResult,
    CapstoneTaskRecord,
    CapstoneTaskResult,
    ChatTurnRecord,
    ChatTurnResult,
    Citation,
    DeepResearchRecord,
    DeepResearchResult,
    HistoryRecord,
    HistoryRepository,
    HistorySummary,
    ImageGenerationResult,
    ImageRecord,
    IngestedDoc,
    PlaygroundRecord,
    PlaygroundResult,
    ProjectId,
    ReportSection,
    ResearchReport,
    SubQuestion,
    ToolInvocation,
    WebAgentRecord,
    WebAgentResult,
    build_history_record,
)
from .llm_client import LLMClient, resolve_model
from .llm_types import Completion, Message, StreamEvent, Usage
from .models import (
    Base,
    CapstoneIngestHistory,
    CapstoneTaskHistory,
    ChatSessionHistory,
    ChatTurnHistory,
    DeepResearchHistory,
    ImageHistory,
    PlaygroundHistory,
    WebAgentHistory,
)
from .persistence import PersistenceOutcome, persist_record
from .search import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    TavilySearch,
    WebResult,
)
from .embeddings import DEFAULT_EMBEDDINGS_TIMEOUT, HFEmbeddings
from .vectorstore import (
    DEFAULT_TOP_K,
    ChromaVectorStore,
    QueryHit,
    VectorRecord,
)
from .sse import (
    format_data,
    format_done,
    format_error,
    format_event,
    format_progress,
    format_sse,
    parse_sse_frame,
)

__all__ = [
    "config",
    "errors",
    "llm_types",
    "llm_client",
    "sse",
    "db",
    "models",
    "history",
    "persistence",
    "search",
    "embeddings",
    "vectorstore",
    "Settings",
    "load_settings",
    "AISharedError",
    "ValidationError",
    "MissingConfigError",
    "LLMTimeoutError",
    "LLMGatewayError",
    "SearchError",
    "EmbeddingsError",
    "ImageProviderError",
    "ImageTimeoutError",
    "PersistenceError",
    # Task 3 — LLM types
    "Message",
    "Usage",
    "Completion",
    "StreamEvent",
    # Task 3 — LLM client
    "LLMClient",
    "resolve_model",
    # Task 3 — SSE helpers
    "format_sse",
    "format_event",
    "format_data",
    "format_progress",
    "format_done",
    "format_error",
    "parse_sse_frame",
    # Task 4 — persistence engine/session lifecycle
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "dispose_engine",
    # Task 4 — ORM models
    "Base",
    "PlaygroundHistory",
    "ChatSessionHistory",
    "ChatTurnHistory",
    "WebAgentHistory",
    "DeepResearchHistory",
    "ImageHistory",
    "CapstoneTaskHistory",
    "CapstoneIngestHistory",
    # Task 4 — history repository + record construction
    "ProjectId",
    "HistoryRepository",
    "HistoryRecord",
    "HistorySummary",
    "build_history_record",
    "Citation",
    "SubQuestion",
    "ReportSection",
    "ResearchReport",
    "ToolInvocation",
    "IngestedDoc",
    "PlaygroundResult",
    "ChatTurnResult",
    "WebAgentResult",
    "DeepResearchResult",
    "ImageGenerationResult",
    "CapstoneTaskResult",
    "CapstoneIngestResult",
    "PlaygroundRecord",
    "ChatTurnRecord",
    "WebAgentRecord",
    "DeepResearchRecord",
    "ImageRecord",
    "CapstoneTaskRecord",
    "CapstoneIngestRecord",
    # Task 4 — persistence-result wrapper (Requirement 12.4)
    "PersistenceOutcome",
    "persist_record",
    # Task 5 — Tavily search wrapper (Requirements 6.1, 6.6, 7.9)
    "TavilySearch",
    "WebResult",
    "DEFAULT_SEARCH_TIMEOUT",
    "DEFAULT_MAX_RESULTS",
    # Task 5 — HF embeddings wrapper (Requirements 7.3, 7.7)
    "HFEmbeddings",
    "DEFAULT_EMBEDDINGS_TIMEOUT",
    # Task 5 — Chroma vector-store wrapper (Requirements 7.3, 9.3)
    "ChromaVectorStore",
    "VectorRecord",
    "QueryHit",
    "DEFAULT_TOP_K",
]

__version__ = "0.1.0"
