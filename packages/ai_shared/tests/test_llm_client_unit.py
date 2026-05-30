"""Unit/example tests for ``ai_shared.llm_client.LLMClient`` happy paths.

These complement the property tests (Properties 1 and 2) by pinning concrete,
successful behaviors of ``complete`` and ``stream`` against a mocked openai-style
client — no live gateway and no real ``openai`` network client is used.
"""

from __future__ import annotations

import asyncio

from ai_shared.llm_client import LLMClient, resolve_model
from ai_shared.llm_types import Completion, Message, StreamEvent

DEFAULT_MODEL = "claude-opus-4.7"


class _FakeSettings:
    llm_base_url = "http://localhost:3090/v1"
    llm_api_key = "test-key"
    llm_model = DEFAULT_MODEL


# --- shaped response doubles ------------------------------------------------


def _usage_obj(prompt: int, completion: int, total: int):
    class _U:
        prompt_tokens = prompt
        completion_tokens = completion
        total_tokens = total

    return _U()


def _completion_obj(text: str, usage=None):
    class _Msg:
        content = text

    class _Choice:
        message = _Msg()

    class _Comp:
        choices = [_Choice()]

    comp = _Comp()
    comp.usage = usage
    return comp


def _stream_chunk(text: str | None, usage=None):
    class _Delta:
        content = text

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]

    c = _Chunk()
    c.usage = usage
    return c


class _AsyncStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._i]
        self._i += 1
        return chunk


class _RecordingCompletions:
    """Records the kwargs of the last ``create`` call and returns a canned result."""

    def __init__(self, result):
        self._result = result
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._result


class _RecordingClient:
    def __init__(self, result):
        self.completions = _RecordingCompletions(result)
        self.chat = type("_Chat", (), {"completions": self.completions})()


def test_complete_returns_text_and_usage() -> None:
    """``complete`` returns the assistant text and maps usage onto output_tokens."""
    comp = _completion_obj("the answer", usage=_usage_obj(11, 4, 15))
    client = LLMClient(_FakeSettings(), client=_RecordingClient(comp))

    result = asyncio.run(client.complete([Message(role="user", content="hi")]))
    assert isinstance(result, Completion)
    assert result.content == "the answer"
    assert result.usage is not None
    assert (result.usage.prompt_tokens, result.usage.output_tokens, result.usage.total_tokens) == (
        11,
        4,
        15,
    )


def test_complete_passes_resolved_model_and_params() -> None:
    """A per-request model overrides the default; temperature/max_tokens pass through."""
    comp = _completion_obj("ok", usage=None)
    rec = _RecordingClient(comp)
    client = LLMClient(_FakeSettings(), client=rec)

    asyncio.run(
        client.complete(
            [Message(role="system", content="s"), Message(role="user", content="u")],
            model="custom-model",
            temperature=0.5,
            max_tokens=256,
        )
    )
    kwargs = rec.completions.last_kwargs
    assert kwargs["model"] == "custom-model"
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 256
    assert kwargs["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


def test_complete_defaults_model_when_absent() -> None:
    """With no per-request model, the configured default is used."""
    rec = _RecordingClient(_completion_obj("ok"))
    client = LLMClient(_FakeSettings(), client=rec)
    asyncio.run(client.complete([Message(role="user", content="u")]))
    assert rec.completions.last_kwargs["model"] == DEFAULT_MODEL


def test_stream_yields_data_then_terminal_done_with_usage() -> None:
    """``stream`` emits a data event per chunk, then a done event carrying usage."""
    chunks = [
        _stream_chunk("Hel"),
        _stream_chunk("lo"),
        _stream_chunk(None, usage=_usage_obj(3, 2, 5)),  # final usage-only chunk
    ]
    client = LLMClient(_FakeSettings(), client=_RecordingClient(_AsyncStream(chunks)))

    async def collect():
        return [ev async for ev in client.stream([Message(role="user", content="hi")])]

    events = asyncio.run(collect())
    assert [e.type for e in events] == ["data", "data", "done"]
    assert [e.data["text"] for e in events if e.type == "data"] == ["Hel", "lo"]
    done = events[-1]
    assert done.data == {"usage": {"prompt_tokens": 3, "output_tokens": 2, "total_tokens": 5}}


def test_stream_requests_usage_and_stream_flags() -> None:
    """The stream call asks for ``stream=True`` and includes usage in the options."""
    rec = _RecordingClient(_AsyncStream([_stream_chunk("x")]))
    client = LLMClient(_FakeSettings(), client=rec)

    async def collect():
        return [ev async for ev in client.stream([Message(role="user", content="hi")])]

    asyncio.run(collect())
    kwargs = rec.completions.last_kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}


def test_stream_done_has_empty_payload_when_no_usage_reported() -> None:
    """When the gateway reports no usage, the done event payload is empty."""
    rec = _RecordingClient(_AsyncStream([_stream_chunk("only")]))
    client = LLMClient(_FakeSettings(), client=rec)

    async def collect():
        return [ev async for ev in client.stream([Message(role="user", content="hi")])]

    events = asyncio.run(collect())
    assert events[-1].type == "done"
    assert events[-1].data == {}
