"""Hugging Face embeddings provider wrapper (Requirements 7.3, 7.7).

:class:`HFEmbeddings` is a thin, framework-agnostic wrapper over the Hugging Face
inference API (via ``huggingface_hub.InferenceClient``) used by Deep Research and
the Capstone RAG pipeline to turn text into vectors with the configured model
(``sentence-transformers/all-MiniLM-L6-v2`` by default,
:attr:`Settings.embedding_model`).

Design constraints honored here:

- **Stable result shape.** :meth:`embed_one` returns a single ``list[float]``;
  :meth:`embed` always returns a batch ``list[list[float]]`` (one vector per input
  text, preserving order), even for a single-element input.
- **Timeout + structured failure.** A per-call timeout (default 30s) is passed to
  the provider, and any failure or timeout is surfaced as
  :class:`~ai_shared.errors.EmbeddingsError` carrying the provider reason
  (Requirements 7.3, 7.7).
- **Dependency isolation / testability.** ``huggingface_hub`` is imported lazily
  (only when a real client is first built), and a client can be injected via the
  ``client=`` constructor argument. This keeps the shaping / error-mapping logic
  unit-testable with a stub — no live ``huggingface_hub`` client and no real
  token are required. The token is read from :attr:`Settings.hf_token`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .config import Settings
from .errors import EmbeddingsError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from huggingface_hub import InferenceClient

__all__ = ["HFEmbeddings", "DEFAULT_EMBEDDINGS_TIMEOUT"]

#: Default per-call embeddings timeout in seconds (Requirement 7.7).
DEFAULT_EMBEDDINGS_TIMEOUT: float = 30.0


def _to_float_vector(raw: Any) -> list[float]:
    """Coerce a single provider vector into a plain ``list[float]``.

    Tolerates numpy arrays (``.tolist()``) and nested singletons (some HF feature-
    extraction responses wrap a single sentence vector as ``[[...]]``). Raises
    ``TypeError``/``ValueError`` indirectly via ``float()`` for non-numeric content,
    which the caller maps onto :class:`EmbeddingsError`.
    """
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    # Unwrap a singleton nesting like [[...]] -> [...].
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 1
        and isinstance(raw[0], (list, tuple))
    ):
        raw = raw[0]
    return [float(x) for x in raw]


def _normalize_batch(raw: Any, expected: int) -> list[list[float]]:
    """Coerce a provider batch response into ``list[list[float]]`` of length ``expected``.

    Accepts a numpy 2-D array or a list of per-text vectors. When the provider
    returns a single flat vector for a single input, it is wrapped into a 1-element
    batch.
    """
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if not isinstance(raw, (list, tuple)):
        raise EmbeddingsError(reason="Embeddings provider returned a non-list response.")

    # Single flat vector returned for a single input -> wrap as one batch row.
    if expected == 1 and raw and not isinstance(raw[0], (list, tuple)):
        return [_to_float_vector(raw)]

    return [_to_float_vector(row) for row in raw]


class HFEmbeddings:
    """Hugging Face embeddings wrapper returning stable float vectors.

    Args:
        settings: Loaded :class:`Settings` providing ``embedding_model`` and
            ``hf_token``.
        client: Optional pre-built client exposing
            ``feature_extraction(text, ...)`` (anything ``InferenceClient``-
            compatible). When omitted, a real ``huggingface_hub.InferenceClient``
            is created lazily on first use. Injecting a stub here keeps the shaping
            / error-mapping logic testable without a live client.
        model: Optional model id override; defaults to ``settings.embedding_model``.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: "InferenceClient | Any | None" = None,
        model: str | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._model = model or settings.embedding_model

    @property
    def model(self) -> str:
        """The embedding model id this wrapper uses."""
        return self._model

    @property
    def client(self) -> "InferenceClient | Any":
        """The underlying inference client, built lazily from settings if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> "InferenceClient":
        """Construct a real ``huggingface_hub.InferenceClient`` from the token."""
        from huggingface_hub import InferenceClient  # noqa: PLC0415 - lazy import

        return InferenceClient(model=self._model, token=self._settings.hf_token)

    def _feature_extraction(self, text: Any, timeout: float) -> Any:
        """Call the client's ``feature_extraction`` for one text or a batch."""
        return self.client.feature_extraction(text, model=self._model)

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout: float = DEFAULT_EMBEDDINGS_TIMEOUT,
    ) -> list[list[float]]:
        """Embed one or more texts, returning one vector per input (batch shape).

        Args:
            texts: The texts to embed. An empty sequence returns ``[]`` without
                calling the provider.
            timeout: Per-call timeout in seconds (Requirement 7.7).

        Returns:
            ``list[list[float]]`` of length ``len(texts)``, preserving input order.

        Raises:
            EmbeddingsError: The provider failed or timed out, or returned an
                unparseable shape; carries the provider reason.
        """
        items = list(texts)
        if not items:
            return []

        try:
            raw = self._feature_extraction(items, timeout=timeout)
        except EmbeddingsError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY provider/transport error
            raise EmbeddingsError(reason=str(exc) or None) from exc

        try:
            return _normalize_batch(raw, expected=len(items))
        except EmbeddingsError:
            raise
        except Exception as exc:  # noqa: BLE001 - unparseable numeric content
            raise EmbeddingsError(
                reason=f"Could not parse embeddings response: {exc}" or None
            ) from exc

    def embed_one(
        self,
        text: str,
        *,
        timeout: float = DEFAULT_EMBEDDINGS_TIMEOUT,
    ) -> list[float]:
        """Embed a single text and return one ``list[float]`` vector.

        Raises:
            EmbeddingsError: The provider failed or timed out; carries the reason.
        """
        batch = self.embed([text], timeout=timeout)
        return batch[0] if batch else []
