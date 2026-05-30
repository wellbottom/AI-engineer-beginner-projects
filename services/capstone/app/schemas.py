"""Request schema and pure task validation for the Capstone service (Requirement 9.9).

``TaskRequest`` is the validated, typed shape the ``POST /task`` handler works with
(the user ``task``). ``validate_task`` is a **pure** function (no I/O, no Agent run,
no LLM call) so it is directly property-testable (Property 28): it returns the
trimmed task when it contains at least one non-whitespace character, and raises
:class:`ai_shared.errors.ValidationError` naming the ``task`` field otherwise — and
because it is pure, a caller that validates *before* starting the Agent guarantees
the Agent is never started on an empty/whitespace-only task (Requirement 9.9).

Validation rule (design "Service: Capstone"; Property 28):

| Field | Rule                                                            |
| ----- | --------------------------------------------------------------- |
| task  | contains ≥ 1 non-whitespace character (``task.strip()`` non-empty) |

Like the Deep Research topic, the design states no upper length bound for a capstone
task, so the only rule is "≥ 1 non-whitespace character" (Requirement 9.9). The
*trimmed* task is returned so the Agent prompt and the persisted record use the
normalized value.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "TaskRequest",
    "validate_task",
    "ACTION",
]

#: Human-readable action label used on validation/error frames.
ACTION = "run task"


@dataclass
class TaskRequest:
    """A validated Capstone task request.

    ``task`` is the trimmed user task (so the Agent prompt and the persisted record
    both use the normalized value).
    """

    task: str


def validate_task(task: object) -> str:
    """Validate a capstone task and return its trimmed value (Property 28).

    Pure function: performs no I/O and never starts the Agent or calls the LLM.
    Succeeds **iff** ``task`` is a string that contains at least one non-whitespace
    character; returns the trimmed task on success.

    Args:
        task: The raw task value from the request body.

    Returns:
        The trimmed task (non-empty).

    Raises:
        ValidationError: Naming the ``task`` field/constraint (Requirement 9.9). The
            caller must validate before starting the Agent so an empty/whitespace
            task never starts a run.
    """
    if not isinstance(task, str):
        raise ValidationError(
            field="task",
            constraint="must be a string",
            action=ACTION,
        )

    trimmed = task.strip()
    if not trimmed:
        raise ValidationError(
            field="task",
            constraint="must contain at least one non-whitespace character",
            action=ACTION,
        )
    return trimmed
