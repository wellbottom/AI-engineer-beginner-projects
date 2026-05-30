"""Request schema and pure topic validation for Deep Research (Requirement 7.8).

``ResearchRequest`` is the validated, typed shape the ``POST /research`` handler
works with (the user ``topic``). ``validate_topic`` is a **pure** function (no I/O,
no decomposition, no search, no LLM call) so it is directly property-testable
(Property 19): it returns the normalized topic when it contains at least one
non-whitespace character, and raises :class:`ai_shared.errors.ValidationError`
naming the ``topic`` field otherwise — and because it is pure, a caller that
validates *before* decomposing/searching guarantees neither the LLM nor Tavily is
ever contacted on invalid input (Requirement 7.8).

Validation rule (design "Service: Deep Research"; Property 19):

| Field | Rule                                                            |
| ----- | --------------------------------------------------------------- |
| topic | contains ≥ 1 non-whitespace character (``topic.strip()`` non-empty) |

Unlike the Web_Agent question (which has an explicit 1–2000 bound), the design
states no upper length bound for a research topic, so the only rule is "≥ 1
non-whitespace character" (Requirement 7.8). The *trimmed* topic is returned so the
decomposition prompt and the persisted record use the normalized value.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "ResearchRequest",
    "validate_topic",
    "ACTION",
]

#: Human-readable action label used on validation/error frames.
ACTION = "research"


@dataclass
class ResearchRequest:
    """A validated Deep Research request.

    ``topic`` is the trimmed user topic (so the decomposition prompt, the search
    queries, and the persisted record all use the normalized value).
    """

    topic: str


def validate_topic(topic: object) -> str:
    """Validate a research topic and return its trimmed value.

    Pure function (Property 19): performs no I/O and never decomposes the topic or
    queries the Search_Provider/LLM_Client. Succeeds **iff** ``topic`` is a string
    that contains at least one non-whitespace character; returns the trimmed topic
    on success.

    Args:
        topic: The raw topic value from the request body.

    Returns:
        The trimmed topic (non-empty).

    Raises:
        ValidationError: Naming the ``topic`` field/constraint (Requirement 7.8).
            The caller must validate before decomposing/searching so an invalid
            topic never triggers decomposition or reaches the Search_Provider.
    """
    if not isinstance(topic, str):
        raise ValidationError(
            field="topic",
            constraint="must be a string",
            action=ACTION,
        )

    trimmed = topic.strip()
    if not trimmed:
        raise ValidationError(
            field="topic",
            constraint="must contain at least one non-whitespace character",
            action=ACTION,
        )
    return trimmed
