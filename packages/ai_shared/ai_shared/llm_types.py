"""Shared LLM message and streaming data models (Requirement 3.10).

These small, framework-agnostic dataclasses are the common vocabulary used by the
shared :class:`~ai_shared.llm_client.LLMClient` and by every backend service that
talks to the LLM_Gateway or streams responses over SSE:

- :class:`Message` — one chat message (``system`` / ``user`` / ``assistant``).
- :class:`Usage` — token accounting reported by the gateway on completion.
- :class:`Completion` — the non-streamed result (text + optional usage).
- :class:`StreamEvent` — the SSE event envelope (``data`` / ``progress`` /
  ``done`` / ``error``) serialized to ``text/event-stream`` by
  :mod:`ai_shared.sse`.

This module is deliberately named ``llm_types`` (not ``models``) so it does not
collide with the SQLAlchemy ORM ``models.py`` added in a later task. It imports
nothing heavy (no ``openai``), so it stays cheap to import and pure to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "Role",
    "MessageDict",
    "EventType",
    "Message",
    "Usage",
    "Completion",
    "StreamEvent",
]

#: Allowed chat roles.
Role = Literal["system", "user", "assistant"]

#: The OpenAI-compatible wire shape for a single chat message.
MessageDict = dict[str, str]

#: Allowed SSE event types in the shared streaming vocabulary.
EventType = Literal["data", "progress", "done", "error"]


@dataclass
class Message:
    """A single chat message exchanged with the LLM_Gateway.

    ``role`` is one of ``"system"``, ``"user"``, or ``"assistant"``; ``content`` is
    the message text.
    """

    role: Role
    content: str

    def to_dict(self) -> MessageDict:
        """Return the OpenAI-compatible ``{"role", "content"}`` wire shape."""
        return {"role": self.role, "content": self.content}


@dataclass
class Usage:
    """Token usage reported by the gateway for a completed response.

    Maps the gateway's ``completion_tokens`` onto :attr:`output_tokens` so the
    field names match the playground's ``done`` event contract (Requirement 4.6).
    """

    prompt_tokens: int
    output_tokens: int
    total_tokens: int

    def to_dict(self) -> dict[str, int]:
        """Serialize to the ``done`` event's ``usage`` payload."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Completion:
    """A non-streamed chat completion: the full text plus optional token usage."""

    content: str
    usage: Usage | None = None


@dataclass
class StreamEvent:
    """The shared SSE event envelope serialized to ``text/event-stream``.

    ``type`` selects the event vocabulary and ``data`` carries the payload:

    - ``data``     → ``{"text": <chunk>}`` (incremental content)
    - ``progress`` → ``{"phase": <str>, "step": <int>, ...}`` (step update)
    - ``done``     → ``{"usage": {...}, ...}`` (terminal success metadata)
    - ``error``    → ``{"action": <str>, "reason": <str>, ...}`` (terminal failure)
    """

    type: EventType
    data: dict = field(default_factory=dict)
