"""Request schema, prompt validation, and the model registry (Requirements 8.3, 8.6).

``ImageRequest`` is the validated, typed shape the ``POST /generate`` handler works
with (the user ``prompt`` plus an optional ``model``). ``validate_image_prompt`` is
a **pure** function (no I/O, no provider call) so it is directly property-testable
(Property 22): it returns the trimmed prompt when it has between 1 and 1000
non-whitespace-trimmed characters, and raises
:class:`ai_shared.errors.ValidationError` naming the violated constraint otherwise —
and because it is pure, a caller that validates *before* calling the Image_Provider
guarantees the provider is never contacted on invalid input (Requirement 8.6).

Validation rule (design "Service: Image Generation Service"; Property 22):

| Field  | Rule                                                          |
| ------ | ------------------------------------------------------------- |
| prompt | 1 <= len(prompt.strip()) <= 1000 (trimmed length in [1,1000]) |

The *trimmed* prompt is returned so the provider request and the persisted record
use the normalized value.

``resolve_image_model`` applies the default model when the user has not selected one
(Requirement 8.3); :data:`SELECTABLE_MODELS` is the list ``GET /models`` exposes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_shared.errors import ValidationError

__all__ = [
    "ImageRequest",
    "validate_image_prompt",
    "validate_image_request",
    "resolve_image_model",
    "PROMPT_MIN",
    "PROMPT_MAX",
    "DEFAULT_MODEL",
    "SELECTABLE_MODELS",
    "ACTION",
]

#: Human-readable action label used on validation/error responses.
ACTION = "generate image"

#: Inclusive trimmed-length bounds for the prompt (Requirement 8.6).
PROMPT_MIN = 1
PROMPT_MAX = 1000

#: The default image-generation model applied when the user selects none
#: (Requirement 8.3). A widely-available Hugging Face text-to-image model.
DEFAULT_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"

#: The selectable model identifiers exposed by ``GET /models`` (Requirement 8.3).
#: The default is listed first. These are real Hugging Face text-to-image model ids.
SELECTABLE_MODELS: list[str] = [
    DEFAULT_MODEL,
    "stabilityai/stable-diffusion-2-1",
    "runwayml/stable-diffusion-v1-5",
    "black-forest-labs/FLUX.1-schnell",
]


@dataclass
class ImageRequest:
    """A validated image-generation request (mirrors the design Data Models).

    ``prompt`` is the trimmed user prompt (so the provider request and the persisted
    record use the normalized value); ``model`` is the resolved model identifier
    (the user's selection, or :data:`DEFAULT_MODEL` when none was selected).
    """

    prompt: str
    model: str


def validate_image_prompt(prompt: object) -> str:
    """Validate an image prompt and return its trimmed value (Property 22).

    Pure function: performs no I/O and never calls the Image_Provider. Succeeds
    **iff** ``prompt`` is a string whose trimmed length is between
    :data:`PROMPT_MIN` and :data:`PROMPT_MAX` inclusive; returns the trimmed prompt
    on success.

    Args:
        prompt: The raw prompt value from the request body.

    Returns:
        The trimmed prompt (1-1000 characters).

    Raises:
        ValidationError: Naming the violated prompt constraint (Requirement 8.6).
            The caller must validate before calling the provider so an invalid
            prompt never reaches the Image_Provider. The constraint distinguishes
            an empty/whitespace-only prompt ("must contain between 1 and 1000
            non-whitespace-trimmed characters") from an over-long one ("must be at
            most 1000 ... characters").
    """
    if not isinstance(prompt, str):
        raise ValidationError(
            field="prompt",
            constraint="must be a string",
            action=ACTION,
        )

    trimmed = prompt.strip()
    if len(trimmed) < PROMPT_MIN:
        raise ValidationError(
            field="prompt",
            constraint=(
                f"must contain between {PROMPT_MIN} and {PROMPT_MAX} "
                "non-whitespace-trimmed characters"
            ),
            action=ACTION,
        )
    if len(trimmed) > PROMPT_MAX:
        raise ValidationError(
            field="prompt",
            constraint=(
                f"must be at most {PROMPT_MAX} non-whitespace-trimmed characters"
            ),
            action=ACTION,
        )
    return trimmed


def resolve_image_model(model: object) -> str:
    """Resolve the model id to use, applying the default when none is selected.

    Pure function (Requirement 8.3): a non-empty, non-whitespace string model id is
    used as-is (trimmed); ``None``/empty/whitespace resolves to :data:`DEFAULT_MODEL`.

    Args:
        model: The user-selected model id, or ``None``/absent.

    Returns:
        The resolved model identifier.

    Raises:
        ValidationError: If ``model`` is provided but is not a string.
    """
    if model is None:
        return DEFAULT_MODEL
    if not isinstance(model, str):
        raise ValidationError(
            field="model",
            constraint="must be a string",
            action=ACTION,
        )
    trimmed = model.strip()
    return trimmed if trimmed else DEFAULT_MODEL


def validate_image_request(payload: dict) -> ImageRequest:
    """Validate a raw request payload into a normalized :class:`ImageRequest`.

    Validates the prompt (Requirement 8.6) and resolves the model (Requirement 8.3)
    without contacting the provider. The prompt is validated first so an invalid
    prompt is reported (and the provider skipped) regardless of the model value.

    Args:
        payload: The raw request body (``prompt`` plus optional ``model``).

    Returns:
        A normalized :class:`ImageRequest` (trimmed prompt + resolved model).

    Raises:
        ValidationError: Naming the violated constraint (Requirement 8.6/8.3).
    """
    prompt = validate_image_prompt(payload.get("prompt"))
    model = resolve_image_model(payload.get("model"))
    return ImageRequest(prompt=prompt, model=model)
