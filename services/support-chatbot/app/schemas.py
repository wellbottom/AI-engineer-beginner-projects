"""Request schema and pure validation for the Support Chatbot (Requirements 5.2, 5.7).

``ChatRequest`` is the validated, typed shape the ``POST /chat`` handler works with
(``session_id`` + the user ``message``). ``validate_message`` is a **pure** function
(no I/O, no LLM call) so it is directly property-testable (Property 9): it returns
the normalized message when it has 1-4000 trimmed characters, and raises
:class:`ai_shared.errors.ValidationError` otherwise — and because it is pure, a
caller that validates *before* calling the LLM_Client guarantees the gateway is
never contacted on invalid input (Requirement 5.7).

Validation rule (design "Service: Customer Support Chatbot"; Property 9):

| Field   | Rule                                                            |
| ------- | --------------------------------------------------------------- |
| message | non-empty after trimming; 1 <= len(trimmed) <= 4000 characters  |

The *trimmed* length is the source of truth for both bounds (Property 9: "1-4,000
non-whitespace-trimmed characters"), so a whitespace-only message is invalid (its
trimmed length is 0) and a message whose trimmed length exceeds 4000 is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "ChatRequest",
    "validate_message",
    "MESSAGE_MIN",
    "MESSAGE_MAX",
    "ACTION",
]

#: Inclusive lower/upper bounds on the trimmed message length (Requirement 5.7).
MESSAGE_MIN = 1
MESSAGE_MAX = 4000

#: Human-readable action label used on validation/error frames.
ACTION = "chat"


@dataclass
class ChatRequest:
    """A validated Support Chatbot chat request.

    ``message`` is the trimmed user message (so the assembled LLM request and the
    persisted turn use the normalized value), and ``session_id`` identifies the
    in-memory + durable conversation.
    """

    session_id: str
    message: str


def validate_message(message: object) -> str:
    """Validate a user message and return its trimmed value.

    Pure function (Property 9): performs no I/O and never calls the LLM_Client.
    Succeeds **iff** ``message`` is a string whose whitespace-trimmed length is
    between 1 and 4,000 inclusive; returns the trimmed message on success.

    Args:
        message: The raw message value from the request body.

    Returns:
        The trimmed message (1-4000 characters).

    Raises:
        ValidationError: Naming the ``message`` field/constraint (Requirement 5.7).
            The caller must validate before contacting the gateway so an invalid
            message never reaches the LLM_Client.
    """
    if not isinstance(message, str):
        raise ValidationError(
            field="message",
            constraint="must be a string",
            action=ACTION,
        )

    trimmed = message.strip()
    if len(trimmed) < MESSAGE_MIN:
        raise ValidationError(
            field="message",
            constraint="must not be empty",
            action=ACTION,
        )
    if len(trimmed) > MESSAGE_MAX:
        raise ValidationError(
            field="message",
            constraint=f"must be at most {MESSAGE_MAX} characters",
            action=ACTION,
        )
    return trimmed
