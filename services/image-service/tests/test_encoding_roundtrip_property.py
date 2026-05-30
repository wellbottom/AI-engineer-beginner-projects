"""Property-based test for image encoding round-trip (Property 20).

# Feature: ai-engineer-practice-monorepo, Property 20: the returned payload declares a web-renderable MIME type and decodes to exactly the original bytes

**Validates: Requirements 8.2**

For any image bytes returned by the Image_Provider,
:func:`app.codec.encode_image` produces a payload that declares a **web-renderable**
MIME type, and :func:`app.codec.decode_image` of that payload yields **exactly** the
original bytes. Base64 is a lossless, total encoding over all byte strings (every
``0x00..0xFF`` value, any length, including empty), so the round-trip holds for
arbitrary image bytes regardless of length or content.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.codec import (
    WEB_RENDERABLE_MIME_TYPES,
    ImageResult,
    decode_image,
    encode_image,
)

# Web-renderable MIME types the encoder is allowed to declare; drawn from the
# service's own allow-list so the test stays in sync with the implementation.
_mime_types = st.sampled_from(sorted(WEB_RENDERABLE_MIME_TYPES))

# Image bytes across the whole space: empty, tiny, and large blobs containing every
# possible byte value (including 0x00) so BYTEA-shaped content is covered.
_image_bytes = st.one_of(
    st.just(b""),  # empty: base64("") == "" round-trips
    st.binary(max_size=2048),  # arbitrary bytes incl. NUL and high bytes
    st.just(bytes(range(256)) * 16),  # all 256 byte values, 4 KB
)


# Feature: ai-engineer-practice-monorepo, Property 20: the returned payload declares a web-renderable MIME type and decodes to exactly the original bytes
@settings(max_examples=300, deadline=None)
@given(image_bytes=_image_bytes, mime_type=_mime_types)
def test_payload_is_web_renderable_and_decodes_to_original_bytes(
    image_bytes: bytes, mime_type: str
) -> None:
    payload = encode_image(image_bytes, mime_type)

    # (1) The payload declares a web-renderable MIME type (Requirement 8.2).
    assert isinstance(payload, ImageResult)
    assert payload.mime_type == mime_type
    assert payload.mime_type in WEB_RENDERABLE_MIME_TYPES

    # (2) Decoding yields EXACTLY the original bytes — from the dataclass payload...
    assert decode_image(payload) == image_bytes
    # ...and from its JSON-able dict form (the shape that crosses the wire).
    assert decode_image(payload.to_json()) == image_bytes

    # The base64 field is ASCII text (so it survives JSON transport unchanged).
    assert payload.data_base64.encode("ascii").decode("ascii") == payload.data_base64
