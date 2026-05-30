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
"""

from __future__ import annotations

from . import config, db, errors, history, llm_client, llm_types, models, persistence, sse
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
]

__version__ = "0.1.0"
