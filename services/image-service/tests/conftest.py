"""Shared fakes/fixtures for the Image Service test suite.

These doubles let the validate -> generate -> encode -> persist flow be tested
without a live ``huggingface_hub`` client (no network/token) or a real Database:

- :class:`FakeImageProvider` — stands in for
  :class:`app.provider.HFImageProvider` by exposing an ``async def generate(prompt,
  model, *, timeout=...) -> bytes`` that records the call and either returns scripted
  PNG bytes or raises a structured :class:`ai_shared.errors.ImageProviderError` /
  :class:`ai_shared.errors.ImageTimeoutError`.
- :class:`FakeHFClient` — a fake ``huggingface_hub``-style client exposing
  ``text_to_image(prompt, *, model=...)`` used to drive the **real**
  :class:`HFImageProvider` (so its conversion / timeout / error-mapping logic is
  exercised). It can return raw bytes, a tiny PIL-style image (``.save``), raise, or
  block to force a timeout.
- :class:`StubRepository` — a :class:`ai_shared.history.HistoryRepository`
  look-alike whose ``save_record`` records calls and can succeed or raise
  :class:`ai_shared.errors.PersistenceError` on demand.
- :func:`make_png_bytes` — a tiny but valid 1x1 PNG byte string for tests that want
  realistic image bytes.
"""

from __future__ import annotations

import time
from typing import Any

from ai_shared.errors import PersistenceError
from ai_shared.history import ProjectId

__all__ = [
    "FakeImageProvider",
    "FakeHFClient",
    "StubRepository",
    "make_png_bytes",
    "TINY_PNG",
]

# A minimal, valid 1x1 transparent PNG (header + IHDR + IDAT + IEND).
TINY_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_png_bytes() -> bytes:
    """Return a small, valid PNG byte string for tests."""
    return TINY_PNG


class FakeImageProvider:
    """Fake HFImageProvider: returns scripted PNG bytes or raises on demand.

    Args:
        image_bytes: The bytes returned by a successful ``generate`` call.
        raise_exc: When set, ``generate`` raises this instead of returning bytes
            (use an ``ImageProviderError`` / ``ImageTimeoutError`` to drive the
            failure paths).
    """

    def __init__(
        self,
        image_bytes: bytes = TINY_PNG,
        *,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._image_bytes = image_bytes
        self._raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        model: str,
        *,
        timeout: float = 60.0,
    ) -> bytes:
        self.calls.append({"prompt": prompt, "model": model, "timeout": timeout})
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._image_bytes


class _PILStyleImage:
    """A minimal PIL-style image exposing ``save(fp, format=...)`` -> PNG bytes."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def save(self, fp, format: str | None = None) -> None:  # noqa: A002 - mirror PIL API
        # We ignore the requested format and just write the canned bytes; the test
        # asserts round-trip equality against these exact bytes.
        fp.write(self._payload)


class FakeHFClient:
    """Fake huggingface_hub-style client driving the REAL HFImageProvider.

    Args:
        returns: What ``text_to_image`` returns — ``bytes`` (used as-is by the
            wrapper) or a PIL-style image (converted to PNG via ``.save``). Ignored
            when ``raise_exc`` or ``block_seconds`` is set.
        raise_exc: When set, ``text_to_image`` raises this (drives the provider-error
            path; a plain ``Exception`` is mapped onto ``ImageProviderError``).
        block_seconds: When set, ``text_to_image`` blocks this many seconds (used
            with a short ``timeout`` to force the timeout path).
        pil_style: When ``True`` and ``returns`` is bytes, wrap them in a PIL-style
            image so the wrapper exercises the ``.save`` conversion branch.
    """

    def __init__(
        self,
        *,
        returns: Any = TINY_PNG,
        raise_exc: BaseException | None = None,
        block_seconds: float | None = None,
        pil_style: bool = False,
    ) -> None:
        self._returns = returns
        self._raise_exc = raise_exc
        self._block_seconds = block_seconds
        self._pil_style = pil_style
        self.calls: list[dict[str, Any]] = []

    def text_to_image(self, prompt: str, *, model: str | None = None, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, "model": model, **kwargs})
        if self._block_seconds is not None:
            time.sleep(self._block_seconds)
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._pil_style and isinstance(self._returns, (bytes, bytearray)):
            return _PILStyleImage(bytes(self._returns))
        return self._returns


class StubRepository:
    """A HistoryRepository look-alike for unit tests (no real Database)."""

    def __init__(self, *, should_fail: bool = False, saved_id: int = 1) -> None:
        self.should_fail = should_fail
        self.saved_id = saved_id
        self.saved: list[tuple[ProjectId, object]] = []

    def save_record(self, project: ProjectId, record: object):
        self.saved.append((project, record))
        if self.should_fail:
            raise PersistenceError(reason="injected failure")
        return self.saved_id
