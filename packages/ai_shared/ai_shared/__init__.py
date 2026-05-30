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
"""

from __future__ import annotations

from . import config, errors, llm_client, llm_types, sse
from .config import Settings, load_settings
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
from .llm_client import LLMClient, resolve_model
from .llm_types import Completion, Message, StreamEvent, Usage
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
]

__version__ = "0.1.0"
