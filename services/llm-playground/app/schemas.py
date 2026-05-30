"""Request schema and pure validation for the LLM Playground (Requirements 4.1, 4.2, 4.7).

``PlaygroundRequest`` is the validated, typed shape the ``POST /generate`` handler
works with (mirrors the design Data Models). ``validate_playground_request`` is a
**pure** function (no I/O, no LLM call) so it is directly property-testable
(Property 3): it returns a normalized :class:`PlaygroundRequest` when every field
is in range, and raises :class:`ai_shared.errors.ValidationError` naming the first
violated field otherwise — and because it is pure, a caller that validates *before*
calling the LLM_Client guarantees the gateway is never contacted on invalid input
(Requirement 4.7).

Validation rules (design "Service: LLM Playground"):

| Field          | Rule                                          |
| -------------- | --------------------------------------------- |
| prompt         | non-empty, length <= 8000                     |
| system_prompt  | length <= 4000 (optional)                     |
| temperature    | 0.0 <= t <= 2.0 (optional, default 1.0)       |
| max_tokens     | 1 <= n <= 4096 (optional, default 1024)       |
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "PlaygroundRequest",
    "validate_playground_request",
    "PROMPT_MAX",
    "SYSTEM_PROMPT_MAX",
    "TEMPERATURE_MIN",
    "TEMPERATURE_MAX",
    "MAX_TOKENS_MIN",
    "MAX_TOKENS_MAX",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_TOKENS",
]

#: Inclusive upper bound on prompt length (Requirement 4.1).
PROMPT_MAX = 8000
#: Inclusive upper bound on the optional system prompt length (Requirement 4.2).
SYSTEM_PROMPT_MAX = 4000
#: Inclusive temperature bounds (Requirement 4.2).
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
#: Inclusive max-output-token bounds (Requirement 4.2).
MAX_TOKENS_MIN = 1
MAX_TOKENS_MAX = 4096

#: Defaults applied when the optional parameter is absent (design defaults).
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 1024

_ACTION = "generate"


@dataclass
class PlaygroundRequest:
    """A validated LLM Playground request (mirrors the design Data Models)."""

    prompt: str
    system_prompt: str | None = None
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    model: str | None = None


def _is_real_number(value: object) -> bool:
    """True for ints/floats but not bools (``bool`` is a subclass of ``int``)."""
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def validate_playground_request(payload: dict) -> PlaygroundRequest:
    """Validate a raw request payload and return a normalized request.

    Pure function (Property 3): performs no I/O and never calls the LLM_Client.
    Succeeds **iff** all of the following hold — the prompt is a non-empty string of
    at most 8,000 characters, the system prompt (when present) is a string of at
    most 4,000 characters, the temperature is within 0.0-2.0 inclusive, and the
    max output tokens is within 1-4,096 inclusive. Optional parameters default to
    ``temperature=1.0`` and ``max_tokens=1024`` when absent/``None``.

    Args:
        payload: The raw request body (``prompt`` plus optional ``system_prompt``,
            ``temperature``, ``max_tokens``, ``model``).

    Returns:
        A normalized :class:`PlaygroundRequest`.

    Raises:
        ValidationError: Naming the first violated field/constraint (Requirement
            4.7). The caller must validate before contacting the gateway so an
            invalid request never reaches the LLM_Client.
    """
    # --- prompt: required, non-empty, <= PROMPT_MAX -----------------------
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValidationError(
            field="prompt",
            constraint="must be a string",
            action=_ACTION,
        )
    if len(prompt) == 0:
        raise ValidationError(
            field="prompt",
            constraint="must not be empty",
            action=_ACTION,
        )
    if len(prompt) > PROMPT_MAX:
        raise ValidationError(
            field="prompt",
            constraint=f"must be at most {PROMPT_MAX} characters",
            action=_ACTION,
        )

    # --- system_prompt: optional, <= SYSTEM_PROMPT_MAX --------------------
    system_prompt = payload.get("system_prompt")
    if system_prompt is not None:
        if not isinstance(system_prompt, str):
            raise ValidationError(
                field="system_prompt",
                constraint="must be a string",
                action=_ACTION,
            )
        if len(system_prompt) > SYSTEM_PROMPT_MAX:
            raise ValidationError(
                field="system_prompt",
                constraint=f"must be at most {SYSTEM_PROMPT_MAX} characters",
                action=_ACTION,
            )

    # --- temperature: optional, 0.0 <= t <= 2.0 ---------------------------
    raw_temperature = payload.get("temperature")
    if raw_temperature is None:
        temperature = DEFAULT_TEMPERATURE
    else:
        if not _is_real_number(raw_temperature):
            raise ValidationError(
                field="temperature",
                constraint="must be a number",
                action=_ACTION,
            )
        temperature = float(raw_temperature)
        if temperature < TEMPERATURE_MIN or temperature > TEMPERATURE_MAX:
            raise ValidationError(
                field="temperature",
                constraint=f"must be between {TEMPERATURE_MIN} and {TEMPERATURE_MAX} inclusive",
                action=_ACTION,
            )

    # --- max_tokens: optional, 1 <= n <= 4096 -----------------------------
    raw_max_tokens = payload.get("max_tokens")
    if raw_max_tokens is None:
        max_tokens = DEFAULT_MAX_TOKENS
    else:
        # Reject bools and non-integers (a float like 12.5 is not a token count).
        if isinstance(raw_max_tokens, bool) or not isinstance(raw_max_tokens, int):
            raise ValidationError(
                field="max_tokens",
                constraint="must be an integer",
                action=_ACTION,
            )
        max_tokens = raw_max_tokens
        if max_tokens < MAX_TOKENS_MIN or max_tokens > MAX_TOKENS_MAX:
            raise ValidationError(
                field="max_tokens",
                constraint=f"must be between {MAX_TOKENS_MIN} and {MAX_TOKENS_MAX} inclusive",
                action=_ACTION,
            )

    # --- model: optional passthrough --------------------------------------
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise ValidationError(
            field="model",
            constraint="must be a string",
            action=_ACTION,
        )

    return PlaygroundRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
    )
