"""Hugging Face image-provider wrapper (Requirements 8.1, 8.3, 8.5, 8.7).

:class:`HFImageProvider` is a thin, framework-agnostic wrapper over the Hugging
Face image-generation capability (``huggingface_hub.InferenceClient.text_to_image``)
used by ``POST /generate``. It does one job: turn a (validated) prompt + model into
raw **PNG bytes**, while honoring the design's failure/timeout contract.

Design constraints honored here:

- **Selected or default model.** The caller passes the already-resolved model id
  (the user's selection or :data:`app.schemas.DEFAULT_MODEL`); the wrapper forwards
  it to ``text_to_image`` (Requirement 8.3).
- **PNG output.** Whatever ``text_to_image`` returns (a PIL ``Image`` in the real
  SDK) is converted to raw PNG bytes via Pillow, so the service produces a single
  web-renderable, durably-storable format (Requirements 8.2, 12.9). If the provider
  already returns ``bytes`` (e.g. a test double), they are used as-is.
- **60s timeout + cancel.** :meth:`generate` runs the blocking provider call in a
  worker thread and waits at most :data:`GENERATE_TIMEOUT` seconds; on expiry it
  stops waiting (cancels the await) and raises :class:`ImageTimeoutError` — so the
  handler returns a timeout error and **no image data** (Requirement 8.7).
- **Structured failure.** Any provider error/unreachable surfaces as
  :class:`ImageProviderError` carrying the provider reason; the handler returns an
  error including that reason and **no image data** (Requirement 8.5).
- **Dependency isolation / testability.** ``huggingface_hub`` is imported lazily
  (only when a real client is first built), and a client can be injected via the
  ``client=`` constructor argument. This keeps the conversion / timeout /
  error-mapping logic unit-testable with a stub — no live ``huggingface_hub`` client
  and no real token are required. The token is read from :attr:`Settings.hf_token`.
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any

from ai_shared.config import Settings
from ai_shared.errors import ImageProviderError, ImageTimeoutError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from huggingface_hub import InferenceClient

__all__ = ["HFImageProvider", "GENERATE_TIMEOUT", "image_to_png_bytes"]

#: Maximum time to wait for an image before cancelling + erroring (Requirement 8.7).
GENERATE_TIMEOUT: float = 60.0


def image_to_png_bytes(image: Any) -> bytes:
    """Convert a provider image result to raw PNG bytes.

    Tolerates the shapes ``text_to_image`` can return:

    - ``bytes``/``bytearray`` — assumed to already be encoded image bytes; returned
      as-is (lets a test double return PNG bytes without Pillow).
    - a PIL ``Image`` (anything exposing ``.save(fp, format=...)``) — saved to an
      in-memory buffer as PNG.

    Raises:
        ImageProviderError: If the result is an unrecognized shape or the
            PNG conversion fails.
    """
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)

    save = getattr(image, "save", None)
    if callable(save):
        try:
            buffer = io.BytesIO()
            save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as exc:  # noqa: BLE001 - map any encoding failure
            raise ImageProviderError(
                reason=f"Failed to encode the generated image as PNG: {exc}"
            ) from exc

    raise ImageProviderError(
        reason=(
            "The image provider returned an unrecognized result type "
            f"({type(image).__name__}); expected image bytes or a PIL Image."
        )
    )


class HFImageProvider:
    """Hugging Face text-to-image wrapper returning raw PNG bytes.

    Args:
        settings: Loaded :class:`Settings` providing ``hf_token``.
        client: Optional pre-built client exposing
            ``text_to_image(prompt, *, model=...)`` (anything ``InferenceClient``-
            compatible). When omitted, a real ``huggingface_hub.InferenceClient`` is
            created lazily on first use. Injecting a stub here keeps the conversion /
            timeout / error-mapping logic testable without a live client.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: "InferenceClient | Any | None" = None,
    ) -> None:
        self._settings = settings
        self._client = client

    @property
    def client(self) -> "InferenceClient | Any":
        """The underlying inference client, built lazily from settings if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> "InferenceClient":
        """Construct a real ``huggingface_hub.InferenceClient`` from the token."""
        from huggingface_hub import InferenceClient  # noqa: PLC0415 - lazy import

        return InferenceClient(token=self._settings.hf_token)

    def _text_to_image_sync(self, prompt: str, model: str) -> bytes:
        """Call ``text_to_image`` (blocking) and return raw PNG bytes.

        Maps any provider/transport error onto :class:`ImageProviderError` with the
        provider reason (Requirement 8.5).
        """
        try:
            image = self.client.text_to_image(prompt, model=model)
        except ImageProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY provider/transport error
            raise ImageProviderError(reason=str(exc) or None) from exc
        return image_to_png_bytes(image)

    async def generate(
        self,
        prompt: str,
        model: str,
        *,
        timeout: float = GENERATE_TIMEOUT,
    ) -> bytes:
        """Generate an image and return its raw PNG bytes, with a hard timeout.

        Runs the blocking ``text_to_image`` call in a worker thread and waits at
        most ``timeout`` seconds. On expiry it cancels the await and raises
        :class:`ImageTimeoutError`; the handler then returns a timeout error with no
        image data (Requirement 8.7).

        Args:
            prompt: The validated, trimmed prompt.
            model: The resolved model id (selected or default).
            timeout: Max seconds to wait (Requirement 8.7; default 60s).

        Returns:
            Raw PNG bytes of the generated image.

        Raises:
            ImageTimeoutError: No image within ``timeout`` seconds.
            ImageProviderError: The provider returned an error or was unreachable.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._text_to_image_sync, prompt, model),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ImageTimeoutError(
                reason=(
                    f"The image provider did not return an image within "
                    f"{timeout:g} seconds."
                ),
                details={"timeout_seconds": timeout, "model": model},
            ) from exc
