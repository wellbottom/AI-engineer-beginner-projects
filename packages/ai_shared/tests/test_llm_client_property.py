"""Property-based tests for the shared LLM client's pure logic.

Covers two design correctness properties:

- **Property 1** (model resolution) — :func:`ai_shared.llm_client.resolve_model`.
- **Property 2** (gateway-failure behavior) — drives a *mocked* gateway through
  error / unreachable / partial-then-fail outcomes and asserts an error indication
  with no fabricated content.

Both run with Hypothesis at >= 100 examples (``max_examples=200``).
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import LLMGatewayError, LLMTimeoutError
from ai_shared.llm_client import LLMClient, resolve_model
from ai_shared.llm_types import Message, StreamEvent

DEFAULT_MODEL = "claude-opus-4.7"

# ---------------------------------------------------------------------------
# Property 1
# ---------------------------------------------------------------------------

# A provided, non-empty model id is any string that is non-whitespace.
_non_empty_model = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
# "Absent" inputs: None, the empty string, or whitespace-only strings.
_absent_model = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=8),
)
_default_strategy = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")


# Feature: ai-engineer-practice-monorepo, Property 1: a provided non-empty model id resolves to itself; absent id resolves to claude-opus-4.7
@settings(max_examples=200, deadline=None)
@given(model=_non_empty_model, default=_default_strategy)
def test_provided_model_resolves_to_itself(model: str, default: str) -> None:
    """A non-empty request model id always resolves to itself, ignoring default."""
    assert resolve_model(model, default) == model


# Feature: ai-engineer-practice-monorepo, Property 1: a provided non-empty model id resolves to itself; absent id resolves to claude-opus-4.7
@settings(max_examples=200, deadline=None)
@given(model=_absent_model)
def test_absent_model_resolves_to_configured_default(model: str | None) -> None:
    """An absent (None/empty/whitespace) model id resolves to the configured default.

    In practice the configured default is ``claude-opus-4.7`` (settings.llm_model).
    """
    assert resolve_model(model, DEFAULT_MODEL) == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Property 2 — mocked-gateway failure harness
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal stand-in for ``Settings`` (only the fields LLMClient reads)."""

    llm_base_url = "http://localhost:3090/v1"
    llm_api_key = "test-key"
    llm_model = DEFAULT_MODEL


def _make_chunk(text: str | None, usage=None):
    """Build a lightweight streaming chunk shaped like an openai delta chunk.

    When ``usage`` is provided, the chunk also carries a usage object (a
    "done-like" signal the client would normally fold into the terminal event).
    """

    class _Delta:
        content = text

    class _Choice:
        delta = _Delta()

    class _Usage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

    class _Chunk:
        choices = [_Choice()]

    chunk = _Chunk()
    chunk.usage = _Usage() if usage else None
    return chunk


class _FailingAsyncStream:
    """An async iterator that yields some real chunks, then raises ``exc``.

    Models a partial stream that fails mid-flight. ``texts`` are emitted as genuine
    ``data`` chunks before ``exc`` is raised, so the test can assert that only
    actually-received content is surfaced — never fabricated/completed text. When
    ``done_like`` is set, a usage-bearing chunk is emitted just before the failure
    so the error also occurs *after a done-like signal*.
    """

    def __init__(self, texts: list[str], exc: BaseException, done_like: bool = False) -> None:
        self._texts = list(texts)
        self._exc = exc
        self._done_like = done_like
        self._i = 0
        self._emitted_done_like = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i < len(self._texts):
            chunk = _make_chunk(self._texts[self._i])
            self._i += 1
            return chunk
        if self._done_like and not self._emitted_done_like:
            self._emitted_done_like = True
            return _make_chunk(None, usage=True)
        raise self._exc


class _FakeCompletions:
    def __init__(self, behavior, stream_texts, exc, done_like=False) -> None:
        self._behavior = behavior
        self._stream_texts = stream_texts
        self._exc = exc
        self._done_like = done_like

    async def create(self, **kwargs):
        # Non-stream call that fails immediately (error / unreachable / timeout).
        if not kwargs.get("stream"):
            raise self._exc
        if self._behavior == "raise_on_create":
            # Connection never established (unreachable).
            raise self._exc
        # behavior == "partial_then_fail": return an async stream that fails late.
        return _FailingAsyncStream(self._stream_texts, self._exc, done_like=self._done_like)


class _FakeClient:
    """Mocked openai-style client exposing ``chat.completions.create``."""

    def __init__(self, behavior, stream_texts, exc, done_like=False) -> None:
        self.chat = type(
            "_Chat",
            (),
            {"completions": _FakeCompletions(behavior, stream_texts, exc, done_like)},
        )()


def _make_exc(kind: str) -> BaseException:
    """Construct a representative gateway exception for ``kind``.

    Uses real ``openai`` SDK exceptions where available so the client's
    timeout-vs-gateway mapping is exercised exactly as in production.
    """
    import httpx
    import openai

    request = httpx.Request("POST", "http://localhost:3090/v1/chat/completions")
    if kind == "timeout":
        return openai.APITimeoutError(request=request)
    if kind == "unreachable":
        return openai.APIConnectionError(message="Connection error.", request=request)
    if kind == "api_error":
        return openai.APIError("gateway boom", request=request, body=None)
    # Generic transport failure not from the SDK.
    return ConnectionError("socket closed")


_EXC_KINDS = ["timeout", "unreachable", "api_error", "generic"]


async def _drain_stream(client: LLMClient, messages):
    """Collect stream events until the client raises; return (events, error)."""
    events: list[StreamEvent] = []
    error: BaseException | None = None
    try:
        async for ev in client.stream(messages):
            events.append(ev)
    except (LLMTimeoutError, LLMGatewayError) as exc:  # mapped errors only
        error = exc
    return events, error


# Feature: ai-engineer-practice-monorepo, Property 2: any gateway error/unreachable/partial-fail yields an error indication and never fabricated content
@settings(max_examples=200, deadline=None)
@given(
    exc_kind=st.sampled_from(_EXC_KINDS),
    mode=st.sampled_from(["complete", "stream_create", "partial_then_fail"]),
    pre_chunks=st.lists(st.text(min_size=1, max_size=8), min_size=0, max_size=5),
    include_done_like=st.booleans(),
)
def test_gateway_failure_yields_error_and_no_fabricated_content(
    exc_kind: str, mode: str, pre_chunks: list[str], include_done_like: bool
) -> None:
    """Every simulated gateway failure surfaces an error and never fabricates text.

    Drives three failure shapes through a mocked client:
      * ``complete``           — non-streamed call fails immediately.
      * ``stream_create``      — the stream cannot even be opened (unreachable).
      * ``partial_then_fail``  — real chunks stream, then the gateway fails (the
        ``include_done_like`` flag appends a usage-like trailing chunk so failure
        can also occur "after a done-like signal").

    Assertions: a mapped ``LLMTimeoutError``/``LLMGatewayError`` is raised (the
    error indication), no terminal ``done`` event is emitted, and the only content
    present is the chunks actually received before the failure — never completed
    or invented text.
    """
    exc = _make_exc(exc_kind)
    messages = [Message(role="user", content="hello")]

    async def scenario() -> None:
        if mode == "complete":
            client = LLMClient(_FakeSettings(), client=_FakeClient("raise_on_create", [], exc))
            with pytest.raises((LLMTimeoutError, LLMGatewayError)) as exc_info:
                await client.complete(messages)
            # The error indication identifies the failed action.
            assert exc_info.value.action == "LLM completion"
            assert exc_info.value.reason  # non-empty human-readable reason
            return

        if mode == "stream_create":
            client = LLMClient(_FakeSettings(), client=_FakeClient("raise_on_create", [], exc))
            events, error = await _drain_stream(client, messages)
            assert error is not None  # an error indication was produced
            assert events == []  # nothing fabricated when the stream never opened
            return

        # partial_then_fail: emit real chunks (optionally a usage-like trailer)
        # and then fail.
        stream_texts = list(pre_chunks)
        client = LLMClient(
            _FakeSettings(),
            client=_FakeClient(
                "partial_then_fail", stream_texts, exc, done_like=include_done_like
            ),
        )
        events, error = await _drain_stream(client, messages)

        # 1) An error indication was produced (mapped to a structured error).
        assert error is not None
        assert isinstance(error, (LLMTimeoutError, LLMGatewayError))
        # 2) NEVER a terminal `done` — a failed stream is not reported as success.
        assert all(ev.type != "done" for ev in events)
        # 3) Only content actually received is present; nothing invented.
        received = [ev.data["text"] for ev in events if ev.type == "data"]
        assert received == stream_texts

        # Timeout exceptions map to LLMTimeoutError, everything else to gateway.
        if exc_kind == "timeout":
            assert isinstance(error, LLMTimeoutError)
        else:
            assert isinstance(error, LLMGatewayError)

    asyncio.run(scenario())
