"""Property-based test: per-sub-question search failure (Property 17).

# Feature: ai-engineer-practice-monorepo, Property 17: a per-sub-question search failure yields an error naming both the failure and the affected sub-question

**Validates: Requirements 7.9**

For any set of sub-questions and any one of them whose Search_Provider request
fails, :func:`app.logic.research_sse` returns a terminal ``error`` frame that
identifies **both** the search failure (a non-empty reason, ``stage: "search"``)
**and** that specific affected sub-question (its text + id). No completed report is
produced and **nothing** is persisted. Because the failure aborts the run at the
failing sub-question, no later sub-question is searched.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.sse import parse_sse_frame
from app.logic import ACTION, PHASE_SEARCH, research_sse

from .conftest import (
    FakeCompleteClient,
    FakeEmbeddings,
    FakeSearch,
    FakeVectorStore,
    StubRepository,
    make_results,
)


def _drain(gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


_reasons = st.sampled_from(
    [
        "provider unavailable",
        "connection refused",
        "search timed out after 30s",
        "rate limited",
        "",
    ]
)


# Feature: ai-engineer-practice-monorepo, Property 17: a per-sub-question search failure yields an error naming both the failure and the affected sub-question
@settings(max_examples=150, deadline=None)
@given(
    n=st.integers(min_value=3, max_value=10),
    fail_index=st.integers(min_value=0, max_value=9),
    reason=_reasons,
)
def test_search_failure_names_failure_and_affected_subquestion(n: int, fail_index: int, reason: str) -> None:
    fail_index = fail_index % n  # which sub-question fails (0-based)
    sub_texts = [f"Sub-question number {i}?" for i in range(1, n + 1)]
    failing_text = sub_texts[fail_index]

    decomposition = "\n".join(sub_texts)
    client = FakeCompleteClient([decomposition])  # only decomposition; no synthesis reached
    # Search fails only for the chosen sub-question; others return results.
    search = FakeSearch(default_results=make_results(2), fail_on=failing_text, fail_reason=reason)
    embeddings = FakeEmbeddings()
    vector_store = FakeVectorStore()
    repo = StubRepository()

    frames = _drain(
        research_sse(
            "some topic",
            client=client,
            search=search,
            embeddings=embeddings,
            vector_store=vector_store,
            repository=repo,
        )
    )

    # Exactly one terminal error frame identifying the search failure + sub-question.
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    err = errors[0]
    assert err["action"] == ACTION
    assert err["stage"] == PHASE_SEARCH
    assert isinstance(err["reason"], str) and err["reason"]  # names the failure
    # Names the specific affected sub-question (both text and id).
    assert err["sub_question"] == failing_text
    assert err["sub_question_id"] == fail_index + 1

    # No completed report (no done) and nothing persisted.
    assert all(etype != "done" for (etype, _) in frames)
    assert repo.saved == []

    # The run aborted at the failing sub-question: it was the LAST search attempted.
    searched = [c["sub_question"] for c in search.calls]
    assert searched == sub_texts[: fail_index + 1]
