"""Property-based test for token-usage exposure on completion (Property 5).

# Feature: ai-engineer-practice-monorepo, Property 5: the done event exposes prompt/output/total token counts exactly as reported

**Validates: Requirements 4.6**

For any completion that reports token usage, the terminal ``done`` event emitted by
:func:`app.logic.generate_sse` exposes the prompt token count, the output token
count, and the total token count **exactly** as reported by the gateway. The test
scripts a :class:`FakeStreamClient` whose terminal ``done`` carries arbitrary usage
counts and asserts the parsed terminal ``done`` frame echoes them verbatim.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.llm_types import StreamEvent
from ai_shared.sse import parse_sse_frame
from app.logic import generate_sse
from app.schemas import PlaygroundRequest

from .conftest import FakeStreamClient, StubRepository

_counts = st.integers(min_value=0, max_value=10_000_000)


def _drain(client, repo) -> list[tuple[str, dict]]:
    request = PlaygroundRequest(prompt="hello", system_prompt=None, temperature=1.0, max_tokens=64)
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in generate_sse(
            request, client, repo, default_model="claude-opus-4.7"
        ):
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


# Feature: ai-engineer-practice-monorepo, Property 5: the done event exposes prompt/output/total token counts exactly as reported
@settings(max_examples=200, deadline=None)
@given(prompt_tokens=_counts, output_tokens=_counts, total_tokens=_counts)
def test_done_exposes_reported_usage_exactly(
    prompt_tokens: int, output_tokens: int, total_tokens: int
) -> None:
    reported = {
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    client = FakeStreamClient(
        [
            StreamEvent(type="data", data={"text": "hi"}),
            StreamEvent(type="done", data={"usage": dict(reported)}),
        ]
    )
    repo = StubRepository()

    frames = _drain(client, repo)
    done_frames = [data for (etype, data) in frames if etype == "done"]

    # Exactly one terminal done event, and it exposes the usage verbatim.
    assert len(done_frames) == 1
    usage = done_frames[0]["usage"]
    assert usage["prompt_tokens"] == prompt_tokens
    assert usage["output_tokens"] == output_tokens
    assert usage["total_tokens"] == total_tokens
