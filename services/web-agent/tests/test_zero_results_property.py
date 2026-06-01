"""Property-based test: zero search results yields a no-sources answer (Property 12).

# Feature: ai-engineer-practice-monorepo, Property 12: zero results yields a no-sources response with an empty citation list

**Validates: Requirements 6.5**

For any question for which the Search_Provider returns zero results,
:func:`app.logic.ask_sse` returns a response stating that no relevant web sources
were found and the citation list is empty — and it does **not** call the LLM_Client
for synthesis.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.sse import parse_sse_frame
from app.logic import NO_SOURCES_MESSAGE, ask_sse

from .conftest import FakeSearch, FakeStreamClient, StubRepository


def _drain(gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


# Feature: ai-engineer-practice-monorepo, Property 12: zero results yields a no-sources response with an empty citation list
@settings(max_examples=200, deadline=None)
@given(question=st.text(min_size=1, max_size=60))
def test_zero_results_yields_no_sources_answer_without_citations(question: str) -> None:
    search = FakeSearch(results=[])  # Search_Provider returns zero results.
    client = FakeStreamClient(  # would-be synthesis events; must NOT be used.
        [],
    )
    repo = StubRepository()

    frames = _drain(
        ask_sse(question, search=search, client=client, repository=repo)
    )

    # The LLM_Client was never called for synthesis (Requirement 6.5).
    assert client.calls == []

    # A no-sources answer was streamed as data.
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    assert data_texts == [NO_SOURCES_MESSAGE]

    # No error frame; exactly one terminal done with an EMPTY citation list.
    assert all(etype != "error" for (etype, _) in frames)
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    assert done[0]["citations"] == []
    assert done[0].get("no_sources") is True
