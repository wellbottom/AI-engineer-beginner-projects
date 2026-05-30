"""Core (non-streamed) image-generation orchestration + persistence.

This module holds the framework-agnostic pieces of ``POST /generate`` so they are
unit/property-testable without spinning up FastAPI, a live ``huggingface_hub``
client, or a real Database. ``POST /generate`` is **non-streamed**: it returns a
single JSON body carrying the web-renderable image and the persistence indication
(design "Service: Image Generation Service").

Flow (the handler has already validated the prompt + resolved the model,
Requirements 8.6/8.3):

1. Call the Image_Provider via :class:`app.provider.HFImageProvider` with the
   resolved model, enforcing a 60s timeout (Requirements 8.1, 8.7).
2. On success: encode the PNG bytes into a web-renderable payload (Requirement 8.2,
   :func:`app.codec.encode_image`), build an :class:`ImageGenerationResult`, and
   persist it best-effort via the shared :func:`ai_shared.persistence.persist_record`
   wrapper (Requirement 12.9) — the image bytes go into the ``BYTEA`` column. The
   persistence indication (``ok`` / ``operation_id``) is merged into the JSON body
   (Requirement 12.4).
3. On a **provider error** (:class:`ImageProviderError`) or a **timeout**
   (:class:`ImageTimeoutError`): raise the structured error so the handler maps it
   to its HTTP status + JSON envelope including the provider reason, and returns
   **no image data** (Requirements 8.5, 8.7). Nothing is persisted (no image was
   produced).

:func:`generate_image` returns the success JSON body dict (it never returns an
error body — errors propagate as exceptions for the handler's shared error handler,
matching the other services). It does not raise for a persistence failure; that
rides in the body as ``persistence: {ok: false, operation_id}`` (Requirement 12.4).
"""

from __future__ import annotations

from typing import Any, Callable

from ai_shared.history import (
    HistoryRepository,
    ImageGenerationResult,
    ProjectId,
    build_history_record,
)
from ai_shared.persistence import persist_record

from .codec import DEFAULT_IMAGE_MIME_TYPE, encode_image
from .provider import HFImageProvider
from .schemas import ImageRequest

__all__ = ["generate_image", "ACTION"]

#: Human-readable action label (kept consistent with the schema/error envelope).
ACTION = "generate image"


async def generate_image(
    request: ImageRequest,
    *,
    provider: HFImageProvider,
    repository: HistoryRepository,
    operation_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Generate one image, persist it best-effort, and return the JSON body.

    Args:
        request: The validated request (trimmed prompt + resolved model).
        provider: The Image_Provider wrapper (real or injected stub) exposing
            ``async generate(prompt, model, *, timeout=...) -> bytes``.
        repository: The shared :class:`HistoryRepository`.
        operation_id_factory: Optional deterministic id factory for tests (passed
            through to the persistence wrapper on failure).

    Returns:
        The success JSON body: the web-renderable image (``mime_type`` +
        ``data_base64``), the ``model`` used, and the ``persistence`` indication.

    Raises:
        ImageProviderError: The provider returned an error (Requirement 8.5). No
            image data is returned and nothing is persisted.
        ImageTimeoutError: No image within the 60s timeout (Requirement 8.7). No
            image data is returned and nothing is persisted.
    """
    # (1) Call the provider (60s timeout enforced inside the wrapper). A provider
    # error / timeout propagates as a structured error -> handled into an error
    # response with the provider reason and NO image data (Requirements 8.5, 8.7).
    png_bytes = await provider.generate(request.prompt, request.model)

    # (2) Encode the PNG bytes into the web-renderable payload (Requirement 8.2).
    image = encode_image(png_bytes, DEFAULT_IMAGE_MIME_TYPE)

    # (3) Persist the generated image best-effort (Requirement 12.9). The image
    # bytes are stored durably as BYTEA; the persistence-failure indication rides in
    # the JSON body, never failing the user-facing result (Requirement 12.4).
    result = ImageGenerationResult(
        prompt=request.prompt,
        model=request.model,
        image_bytes=png_bytes,
        mime_type=image.mime_type,
    )
    record = build_history_record(ProjectId.IMAGE, result)
    kwargs = (
        {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    )
    outcome = persist_record(repository, ProjectId.IMAGE, record, **kwargs)

    body: dict[str, Any] = {
        "mime_type": image.mime_type,
        "data_base64": image.data_base64,
        "model": request.model,
    }
    return outcome.attach_to_body(body)
