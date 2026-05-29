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
"""

from __future__ import annotations

from . import config, errors
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

__all__ = [
    "config",
    "errors",
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
]

__version__ = "0.1.0"
