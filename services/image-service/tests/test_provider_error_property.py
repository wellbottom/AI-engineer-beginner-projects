"""Property-based test: provider error/timeout yields a reason and no image data (Property 21).

# Feature: ai-engineer-practice-monorepo, Property 21: any provider error yields an error including the provider reason and no image data

**Validates: Requirements 8.5**

For any simulated Image_Provider failure — a provider error (Requirement 8.5) or a
60s timeout (Requirement 8.7) — the image-generation flow raises the structured
error (which the FastAPI handler maps to the shared ``{"error": {...}}`` envelope),
the error **includes the provider reason**, the surfaced response carries **no image
data** (no ``data_base64`` / ``mime_type`` payload), and **nothing is persisted**
(no image was produced).

Two angles are exercised across the input space:

1. The **real** :class:`app.provider.HFImageProvider` driven by a fake HF client
   whose ``text_to_image`` raises an arbitrary exception — proving any provider
   exception is mapped onto :class:`ImageProviderError` carrying the reason.
2. The full :func:`app.logic.generate_image` flow with a provider that raises a
   structured :class:`ImageProviderError` / :class:`ImageTimeoutError` — proving the
   error propagates, no image data is built, and the repository is never written.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.config import Settings
from ai_shared.errors import ImageProviderError, ImageTimeoutError
from app.logic import generate_image
from app.provider import HFImageProvider
from app.schemas import DEFAULT_MODEL, ImageRequest

from .conftest import FakeHFClient, FakeImageProvider, StubRepository

# Keys that would carry image data in a success body; an error must carry NONE.
_IMAGE_DATA_KEYS = ("data_base64", "mime_type")


def _settings() -> Settings:
    """Minimal Settings for constructing the real provider (no real token used)."""
    return Settings(
        llm_base_url="http://localhost:3090/v1",
        llm_api_key="test",
        llm_model="claude-opus-4.7",
        tavily_api_key="test",
        hf_token="test",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        chroma_path="./.chroma",
        db_host="localhost",
        db_port=5432,
        db_user="u",
        db_password="p",
        db_name="d",
    )


# Reasons span typical provider failures plus the empty reason (which falls back to
# the error type's default, non-empty reason).
_reasons = st.one_of(
    st.sampled_from(
        [
            "model is currently loading",
            "503 Service Unavailable",
            "connection refused",
            "invalid model id",
            "rate limited",
        ]
    ),
    st.text(max_size=80),  # arbitrary text, including the empty string
)


# Feature: ai-engineer-practice-monorepo, Property 21: any provider error yields an error including the provider reason and no image data
@settings(max_examples=150, deadline=None)
@given(reason=_reasons)
def test_real_provider_maps_any_exception_to_provider_error_with_reason(reason: str) -> None:
    """The real HFImageProvider maps ANY provider exception to ImageProviderError."""
    client = FakeHFClient(raise_exc=RuntimeError(reason))
    provider = HFImageProvider(_settings(), client=client)

    raised: ImageProviderError | None = None
    try:
        asyncio.run(provider.generate("a prompt", DEFAULT_MODEL))
    except ImageProviderError as exc:
        raised = exc

    assert raised is not None
    # The error carries a non-empty reason; a supplied non-empty reason is preserved.
    assert isinstance(raised.reason, str) and raised.reason
    if reason:
        assert raised.reason == reason
    # The shared envelope carries NO image data.
    envelope = raised.to_dict()
    assert set(envelope) == {"error"}
    assert not (_IMAGE_DATA_KEYS[0] in envelope or _IMAGE_DATA_KEYS[1] in envelope)


# Feature: ai-engineer-practice-monorepo, Property 21: any provider error yields an error including the provider reason and no image data
@settings(max_examples=150, deadline=None)
@given(
    reason=_reasons,
    kind=st.sampled_from(["provider", "timeout"]),
)
def test_generate_flow_error_carries_reason_no_image_data_and_no_persist(
    reason: str, kind: str
) -> None:
    """generate_image propagates a provider error/timeout with the reason, no image
    data, and persists nothing."""
    if kind == "provider":
        exc: ImageProviderError | ImageTimeoutError = ImageProviderError(reason=reason or None)
        expected_status = 502
    else:
        exc = ImageTimeoutError(reason=reason or None)
        expected_status = 504

    provider = FakeImageProvider(raise_exc=exc)
    repo = StubRepository()
    request = ImageRequest(prompt="a scenic mountain", model=DEFAULT_MODEL)

    raised: ImageProviderError | ImageTimeoutError | None = None
    try:
        asyncio.run(generate_image(request, provider=provider, repository=repo))
    except (ImageProviderError, ImageTimeoutError) as e:
        raised = e

    # (1) The structured error propagated (the handler maps it to its HTTP status).
    assert raised is not None
    assert type(raised) is type(exc)
    assert raised.http_status == expected_status

    # (2) The error includes a (non-empty) provider reason.
    assert isinstance(raised.reason, str) and raised.reason
    if reason:
        assert raised.reason == reason

    # (3) The surfaced envelope carries NO image data.
    envelope = raised.to_dict()
    assert set(envelope) == {"error"}
    error_obj = envelope["error"]
    assert _IMAGE_DATA_KEYS[0] not in error_obj
    assert _IMAGE_DATA_KEYS[1] not in error_obj

    # (4) The provider was contacted but nothing was persisted (no image produced).
    assert len(provider.calls) == 1
    assert repo.saved == []


def test_real_provider_timeout_mechanism_raises_timeout_with_no_image_data() -> None:
    """The real provider's hard timeout (Requirement 8.7) fires when text_to_image
    blocks past the deadline, raising ImageTimeoutError with a reason and no bytes.

    Uses a short timeout override (the wrapper's default is the 60s contract) so the
    test is fast; the mechanism (``asyncio.wait_for`` cancelling the blocked call) is
    identical to the production 60s path.
    """
    client = FakeHFClient(block_seconds=5.0)  # blocks far past the short timeout
    provider = HFImageProvider(_settings(), client=client)

    raised: ImageTimeoutError | None = None
    try:
        asyncio.run(provider.generate("a prompt", DEFAULT_MODEL, timeout=0.2))
    except ImageTimeoutError as exc:
        raised = exc

    assert raised is not None
    assert raised.http_status == 504
    assert isinstance(raised.reason, str) and raised.reason
    # The timeout error names the configured timeout + model in its details, and the
    # envelope carries no image data.
    assert raised.details.get("timeout_seconds") == 0.2
    assert raised.details.get("model") == DEFAULT_MODEL
    envelope = raised.to_dict()
    assert _IMAGE_DATA_KEYS[0] not in envelope["error"]
    assert _IMAGE_DATA_KEYS[1] not in envelope["error"]
