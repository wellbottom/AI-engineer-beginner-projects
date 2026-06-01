"""Request schema and pure question validation for the Web Agent (Requirement 6.7).

``AskRequest`` is the validated, typed shape the ``POST /ask`` handler works with
(the user ``question``). ``validate_question`` is a **pure** function (no I/O, no
search, no LLM call) so it is directly property-testable (Property 14): it returns
the normalized question when it has 1-2000 trimmed characters, and raises
:class:`ai_shared.errors.ValidationError` naming the ``question`` field otherwise —
and because it is pure, a caller that validates *before* querying the
Search_Provider guarantees Tavily is never contacted on invalid input
(Requirement 6.7).

Validation rule (design "Service: Ask the Web Agent"; Property 14):

| Field    | Rule                                                            |
| -------- | --------------------------------------------------------------- |
| question | non-empty after trimming; 1 <= len(trimmed) <= 2000 characters  |

The *trimmed* length is the source of truth for both bounds (Property 14: "1-2,000
non-whitespace-trimmed characters"), so a whitespace-only question is invalid (its
trimmed length is 0) and a question whose trimmed length exceeds 2000 is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "AskRequest",
    "validate_question",
    "QUESTION_MIN",
    "QUESTION_MAX",
    "ACTION",
]

#: Inclusive lower/upper bounds on the trimmed question length (Requirement 6.7).
QUESTION_MIN = 1
QUESTION_MAX = 2000

#: Human-readable action label used on validation/error frames.
ACTION = "ask"


@dataclass
class AskRequest:
    """A validated Web Agent ask request.

    ``question`` is the trimmed user question (so the search query, the LLM request,
    and the persisted record all use the normalized value).
    """

    question: str


def validate_question(question: object) -> str:
    """Validate a user question and return its trimmed value.

    Pure function (Property 14): performs no I/O and never queries the
    Search_Provider or the LLM_Client. Succeeds **iff** ``question`` is a string
    whose whitespace-trimmed length is between 1 and 2,000 inclusive; returns the
    trimmed question on success.

    Args:
        question: The raw question value from the request body.

    Returns:
        The trimmed question (1-2000 characters).

    Raises:
        ValidationError: Naming the ``question`` field/constraint (Requirement
            6.7). The caller must validate before contacting Tavily so an invalid
            question never reaches the Search_Provider.
    """
    if not isinstance(question, str):
        raise ValidationError(
            field="question",
            constraint="must be a string",
            action=ACTION,
        )

    trimmed = question.strip()
    if len(trimmed) < QUESTION_MIN:
        raise ValidationError(
            field="question",
            constraint="must not be empty",
            action=ACTION,
        )
    if len(trimmed) > QUESTION_MAX:
        raise ValidationError(
            field="question",
            constraint=f"must be at most {QUESTION_MAX} characters",
            action=ACTION,
        )
    return trimmed
