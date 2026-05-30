"""Unit/example tests for ``ai_shared.embeddings.HFEmbeddings`` (Task 5.1).

These pin concrete behaviors of the HF embeddings wrapper against an injected stub
client — no live ``huggingface_hub`` client, no network, and no real token. They
cover:

- single + batch return the expected ``list[float]`` / ``list[list[float]]`` shape,
- order is preserved across a batch,
- empty input returns ``[]`` without calling the provider,
- a single flat vector returned for a single input is wrapped into a batch row,
- numpy-like arrays (``.tolist()``) are coerced,
- ``EmbeddingsError`` on a provider failure/timeout, surfacing the reason,
- ``EmbeddingsError`` on an unparseable (non-numeric) response.
"""

from __future__ import annotations

import pytest

from ai_shared.embeddings import HFEmbeddings
from ai_shared.errors import EmbeddingsError


class _FakeSettings:
    embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
    hf_token = "test-token"


class _StubClient:
    """Returns a canned feature-extraction result and records the call."""

    def __init__(self, result):
        self._result = result
        self.calls: list = []

    def feature_extraction(self, text, **kwargs):
        self.calls.append(text)
        return self._result


class _RaisingClient:
    def __init__(self, exc: BaseException):
        self._exc = exc

    def feature_extraction(self, text, **kwargs):
        raise self._exc


class _FakeNDArray:
    """Minimal numpy-like stand-in exposing ``.tolist()``."""

    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


def test_embed_one_returns_flat_float_vector() -> None:
    """embed_one returns a single list[float]."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([[0.1, 0.2, 0.3]]))
    vec = emb.embed_one("hello")
    assert vec == [0.1, 0.2, 0.3]
    assert all(isinstance(x, float) for x in vec)


def test_embed_one_unwraps_singleton_nesting() -> None:
    """A single flat vector returned for one input is handled by embed_one."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([0.5, 0.6]))
    assert emb.embed_one("x") == [0.5, 0.6]


def test_embed_batch_returns_one_vector_per_text_in_order() -> None:
    """embed returns list[list[float]] of len(texts), preserving order."""
    result = [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]]
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient(result))
    out = emb.embed(["a", "b", "c"])
    assert out == [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]]


def test_embed_empty_list_skips_provider() -> None:
    """An empty input returns [] without calling the provider."""
    stub = _StubClient([[9.9]])
    emb = HFEmbeddings(_FakeSettings(), client=stub)
    assert emb.embed([]) == []
    assert stub.calls == []


def test_embed_coerces_ints_to_floats() -> None:
    """Integer-valued vectors are coerced to floats."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([[1, 2, 3]]))
    out = emb.embed(["x"])
    assert out == [[1.0, 2.0, 3.0]]
    assert all(isinstance(v, float) for v in out[0])


def test_embed_handles_numpy_like_arrays() -> None:
    """A numpy-like batch (``.tolist()``) is coerced to nested float lists."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient(_FakeNDArray([[0.1, 0.2]])))
    assert emb.embed(["x"]) == [[0.1, 0.2]]


def test_embed_single_flat_vector_wrapped_to_batch_row() -> None:
    """When one input yields a flat vector, embed wraps it as a 1-row batch."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([0.7, 0.8, 0.9]))
    assert emb.embed(["only"]) == [[0.7, 0.8, 0.9]]


def test_provider_failure_raises_embeddings_error_with_reason() -> None:
    """A provider exception maps to EmbeddingsError surfacing the reason."""
    emb = HFEmbeddings(_FakeSettings(), client=_RaisingClient(RuntimeError("hf down")))
    with pytest.raises(EmbeddingsError) as ei:
        emb.embed(["x"])
    assert "hf down" in ei.value.reason


def test_provider_timeout_raises_embeddings_error() -> None:
    """A timeout maps to EmbeddingsError."""
    emb = HFEmbeddings(_FakeSettings(), client=_RaisingClient(TimeoutError("slow")))
    with pytest.raises(EmbeddingsError) as ei:
        emb.embed_one("x", timeout=30.0)
    assert "slow" in ei.value.reason


def test_unparseable_response_raises_embeddings_error() -> None:
    """A non-numeric response is surfaced as EmbeddingsError, not a raw ValueError."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([["not-a-number"]]))
    with pytest.raises(EmbeddingsError):
        emb.embed(["x"])


def test_non_list_response_raises_embeddings_error() -> None:
    """A scalar/None response is surfaced as EmbeddingsError."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient(None))
    with pytest.raises(EmbeddingsError):
        emb.embed(["x"])


def test_model_defaults_to_settings_embedding_model() -> None:
    """The wrapper uses the configured embedding model by default."""
    emb = HFEmbeddings(_FakeSettings(), client=_StubClient([[0.0]]))
    assert emb.model == "sentence-transformers/all-MiniLM-L6-v2"
