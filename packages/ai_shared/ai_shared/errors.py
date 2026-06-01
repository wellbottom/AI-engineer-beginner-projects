"""Structured, framework-agnostic error hierarchy for the AI Engineer Practice
Monorepo backend services.

Every error carries an ``action`` (the human-readable operation that failed), a
``reason`` (why it failed), and optional ``details`` (structured context). Each
error type also declares the HTTP status a service should map it to when it is
surfaced over HTTP. None of these types import FastAPI (or any web framework):
services translate ``http_status`` / ``to_dict()`` into their own responses.

JSON envelope produced by :meth:`AISharedError.to_dict`::

    {"error": {"action": ..., "reason": ..., "details": {...}}}

Maps to the design's ``errors.py`` section (Requirements 3.7, 3.8) and is used by
``config.load_settings`` for the startup-validation abort (Requirement 3.9).
"""

from __future__ import annotations

from typing import Any

__all__ = [
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


class AISharedError(Exception):
    """Base class for all structured ``ai_shared`` errors.

    Subclasses set :attr:`http_status` (the HTTP status a service should return
    when surfacing the error, or ``None`` when the error is not served over HTTP,
    e.g. a startup abort), :attr:`default_action`, and :attr:`default_reason`.
    """

    #: HTTP status code a service maps this error to (``None`` => not HTTP-served).
    http_status: int | None = 500
    #: Default human-readable label for the failed operation.
    default_action: str = "operation"
    #: Default human-readable failure reason.
    default_reason: str = "An unexpected error occurred."

    def __init__(
        self,
        action: str | None = None,
        reason: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.action: str = action or self.default_action
        self.reason: str = reason or self.default_reason
        self.details: dict[str, Any] = dict(details) if details else {}
        super().__init__(self.reason)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the shared JSON error envelope."""
        return {
            "error": {
                "action": self.action,
                "reason": self.reason,
                "details": dict(self.details),
            }
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"{type(self).__name__}(action={self.action!r}, reason={self.reason!r}, "
            f"details={self.details!r})"
        )


class ValidationError(AISharedError):
    """A request parameter violated a constraint (HTTP 422).

    Carries the offending ``field`` and the violated ``constraint`` so callers can
    name the invalid parameter without sending the request downstream.
    """

    http_status = 422
    default_action = "request validation"
    default_reason = "A request parameter is invalid."

    def __init__(
        self,
        field: str,
        constraint: str,
        *,
        action: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.field = field
        self.constraint = constraint
        merged: dict[str, Any] = {"field": field, "constraint": constraint}
        if details:
            merged.update(details)
        super().__init__(
            action=action,
            reason=reason or f"{field} {constraint}",
            details=merged,
        )


class MissingConfigError(AISharedError):
    """One or more required environment variables were absent at startup.

    This aborts service startup before any request is served (Requirement 3.9);
    it is therefore not surfaced over HTTP, so :attr:`http_status` is ``None``.
    :attr:`names` lists exactly the absent required variables (Requirement 3.13).
    """

    http_status = None
    default_action = "startup configuration"
    default_reason = "Required configuration is missing."

    def __init__(
        self,
        names: list[str],
        *,
        action: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.names: list[str] = list(names)
        merged: dict[str, Any] = {"names": list(names)}
        if details:
            merged.update(details)
        joined = ", ".join(self.names) if self.names else "(none)"
        super().__init__(
            action=action,
            reason=reason or f"Missing required environment variables: {joined}",
            details=merged,
        )


class LLMTimeoutError(AISharedError):
    """The LLM gateway did not respond within the configured timeout (HTTP 504)."""

    http_status = 504
    default_action = "LLM completion"
    default_reason = "The LLM gateway did not respond within the time limit."


class LLMGatewayError(AISharedError):
    """The LLM gateway returned an error or was unreachable (HTTP 502)."""

    http_status = 502
    default_action = "LLM completion"
    default_reason = "The LLM gateway returned an error or was unreachable."


class SearchError(AISharedError):
    """The web search provider failed (HTTP 502).

    ``sub_question`` is set by Deep Research to identify the affected sub-question.
    """

    http_status = 502
    default_action = "web search"
    default_reason = "The search provider failed."

    def __init__(
        self,
        action: str | None = None,
        reason: str | None = None,
        *,
        sub_question: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.sub_question = sub_question
        merged: dict[str, Any] = {}
        if sub_question is not None:
            merged["sub_question"] = sub_question
        if details:
            merged.update(details)
        super().__init__(action=action, reason=reason, details=merged or None)


class EmbeddingsError(AISharedError):
    """The embeddings service failed (HTTP 502)."""

    http_status = 502
    default_action = "embeddings"
    default_reason = "The embeddings service failed."


class ImageProviderError(AISharedError):
    """The image provider returned an error (HTTP 502)."""

    http_status = 502
    default_action = "image generation"
    default_reason = "The image provider returned an error."


class ImageTimeoutError(AISharedError):
    """The image provider did not return an image within the time limit (HTTP 504)."""

    http_status = 504
    default_action = "image generation"
    default_reason = "The image provider did not return an image within the time limit."


class PersistenceError(AISharedError):
    """Persisting (or reading) a History_Record failed.

    For a completed operation this is caught by the service and never fails the
    user-facing result (Requirement 12.4 policy). For ``GET /history*`` retrieval
    endpoints it maps to HTTP 502 (Requirement 13.6).
    """

    http_status = 502
    default_action = "history persistence"
    default_reason = "Persisting the history record failed."
