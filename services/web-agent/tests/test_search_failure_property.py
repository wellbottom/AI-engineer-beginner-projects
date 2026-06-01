"""Property-based test: search failure/timeout yields only an error (Property 13).

# Feature: ai-engineer-practice-monorepo, Property 13: any search failure/timeout yields only an error identifying the failure, no answer, empty citations

**Validates: Requirements 6.6**

For any simulated Search_Provider failure or 30s timeout, :func:`app.logic.ask_sse`
returns only an ``error`` frame identifying the search failure, produces no
synthesized answer (no ``data``/``done`` frames), and persists nothing. Because the
``SearchError`` is raised before any synthesis, the LLM_Client is never called.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import SearchError
from ai_shared.sse import parse_sse_frame
from app.logic import ACTION, ask_sse

from .conftest import FakeSearch, FakeStreamClient, StubRepository


def _drain(gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


# Distinct provider-failure reasons, incl. a 30s-timeout phrasing (Requirement 6.6).
_reasons = st.sampled_from(
    [
        "provider unavailable",
        "connection refused",
        "search timed out after 30s",
        "rate limited",
        "",
    ]
)


# Feature: ai-engineer-practice-monorepo, Property 13: any search failure/timeout yields only an error identifying the failure, no answer, empty citations
@settings(max_examples=200, deadline=None)
@given(question=st.text(min_size=1, max_size=60), reason=_reasons)
def test_search_failure_yields_only_error_no_answer_no_citations(
    question: str, reason: str
) -> None:
    # The SearchError reason defaults when empty (the shared error supplies a
    # human-readable default), matching the wrapper's behavior.
    exc = SearchError(reason=reason or None)
    search = FakeSearch(raise_exc=exc)
    client = FakeStreamClient([])  # must NOT be called.
    repo = StubRepository()

    frames = _drain(
        ask_sse(question, search=search, client=client, repository=repo)
    )

    # Exactly one terminal error frame identifying the search failure.
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == ACTION
    assert errors[0]["stage"] == "search"
    assert isinstance(errors[0]["reason"], str) and errors[0]["reason"]

    # No synthesized answer: no data frames and no terminal done.
    assert all(etype not in ("data", "done") for (etype, _) in frames)

    # The LLM_Client was never called and nothing was persisted (empty citations).
    assert client.calls == []
    assert repo.saved == []
