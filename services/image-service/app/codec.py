"""Web-renderable image payload encoding/decoding (Requirement 8.2; Property 20).

The Image_Provider (Hugging Face ``text_to_image``) yields a decoded image; the
provider wrapper (:mod:`app.provider`) converts it to raw **PNG bytes**. These pure
helpers turn those raw bytes into the web-renderable payload the Shared_Frontend can
render directly — a ``{mime_type, data_base64}`` object whose ``data_base64`` is the
standard base64 of the exact image bytes — and decode that payload back to the
original bytes.

Why this shape (Requirement 8.2): the frontend builds a ``data:<mime_type>;base64,
<data_base64>`` URL and assigns it to an ``<img src>``; no further conversion is
needed. PNG is a universally web-renderable raster format and is what the service
produces and stores durably as ``BYTEA`` (Requirement 12.9), so the history detail
endpoint can re-emit the identical payload.

Round-trip guarantee (Property 20): for any image bytes ``b`` and web-renderable
``mime_type``, ``decode_image(encode_image(b, mime_type))`` returns exactly ``b``
and the encoded payload's ``mime_type`` is one of :data:`WEB_RENDERABLE_MIME_TYPES`.
Base64 is a lossless, total encoding over all byte strings (every ``0x00..0xFF``
value, any length, including empty), so the round-trip holds for arbitrary image
bytes.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ImageResult",
    "encode_image",
    "decode_image",
    "WEB_RENDERABLE_MIME_TYPES",
    "DEFAULT_IMAGE_MIME_TYPE",
]

#: The MIME type the service produces and stores (PNG — universally web-renderable).
DEFAULT_IMAGE_MIME_TYPE = "image/png"

#: MIME types a browser ``<img>`` can render directly from a ``data:`` URL. The
#: encoded payload's ``mime_type`` is always one of these so the frontend never has
#: to convert (Requirement 8.2).
WEB_RENDERABLE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/svg+xml",
        "image/avif",
    }
)


@dataclass
class ImageResult:
    """A web-renderable image payload (mirrors the design ``ImageResult``).

    ``mime_type`` is a web-renderable MIME type (in practice ``image/png``) and
    ``data_base64`` is the standard base64 encoding of the exact image bytes, so the
    frontend can render ``data:<mime_type>;base64,<data_base64>`` without converting.
    """

    mime_type: str
    data_base64: str

    def to_json(self) -> dict[str, str]:
        """Serialize to the JSON object returned to the Shared_Frontend."""
        return {"mime_type": self.mime_type, "data_base64": self.data_base64}


def encode_image(
    image_bytes: bytes,
    mime_type: str = DEFAULT_IMAGE_MIME_TYPE,
) -> ImageResult:
    """Encode raw image bytes into a web-renderable :class:`ImageResult`.

    Pure function (Property 20). The image bytes are base64-encoded (standard,
    padded alphabet) and paired with a web-renderable MIME type so the frontend can
    display the result directly. ``decode_image`` is the exact inverse.

    Args:
        image_bytes: The raw image bytes (PNG produced by the provider wrapper, or
            any image bytes). May be empty; base64 of ``b""`` is ``""``.
        mime_type: The image's MIME type. Must be web-renderable (Requirement 8.2);
            defaults to ``image/png``.

    Returns:
        An :class:`ImageResult` whose ``data_base64`` decodes to exactly
        ``image_bytes`` and whose ``mime_type`` is web-renderable.

    Raises:
        TypeError: If ``image_bytes`` is not ``bytes``/``bytearray``.
        ValueError: If ``mime_type`` is not a web-renderable MIME type.
    """
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise TypeError(
            f"image_bytes must be bytes, got {type(image_bytes).__name__}"
        )
    if mime_type not in WEB_RENDERABLE_MIME_TYPES:
        raise ValueError(
            f"mime_type {mime_type!r} is not a web-renderable image MIME type"
        )
    data_base64 = base64.b64encode(bytes(image_bytes)).decode("ascii")
    return ImageResult(mime_type=mime_type, data_base64=data_base64)


def decode_image(payload: "ImageResult | dict[str, Any]") -> bytes:
    """Decode a web-renderable payload back to the original image bytes.

    Pure inverse of :func:`encode_image`. Accepts either an :class:`ImageResult` or
    a plain ``{"data_base64": ...}`` dict (e.g. parsed from JSON).

    Args:
        payload: The encoded payload (an :class:`ImageResult` or a dict carrying a
            ``data_base64`` string).

    Returns:
        The original image bytes (``decode_image(encode_image(b, m)) == b``).

    Raises:
        TypeError: If ``payload`` lacks a string ``data_base64``.
        ValueError: If ``data_base64`` is not valid base64.
    """
    if isinstance(payload, ImageResult):
        data_base64 = payload.data_base64
    elif isinstance(payload, dict):
        data_base64 = payload.get("data_base64")
    else:
        raise TypeError(
            f"payload must be ImageResult or dict, got {type(payload).__name__}"
        )

    if not isinstance(data_base64, str):
        raise TypeError("payload is missing a string 'data_base64' field")

    try:
        # validate=True rejects non-alphabet characters so a malformed payload is a
        # clear error rather than silently dropping bytes.
        return base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"data_base64 is not valid base64: {exc}") from exc
