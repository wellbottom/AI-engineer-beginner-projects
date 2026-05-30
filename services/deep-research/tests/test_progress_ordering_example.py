"""Example/unit test: per-step research progress ordering (Requirement 7.6).

**Validates: Requirements 7.6**

This is an example (NOT a property) test. Requirement 7.6 says that while research is
in progress, the Deep_Research service streams **one** progress update per completed
step over SSE, where a *step* is one of: the topic **decomposition**, a
**per-sub-question Search_Provider query**, a **per-sub-question embedding storage**,
or the **report synthesis**.

Driving :func:`app.logic.research_sse` with fully MOCKED/stubbed collaborators (the
same fakes the sibling failure tests use — no network, no real LLM/Tavily/HF/Chroma,
and a stubbed ``HistoryRepository``), this asserts that for ``n`` decomposed
sub-questions the emitted ``progress`` frames are, **in order**::

    decomposition
    (search, embedding)  x n      # one search then one embedding per sub-question
    synthesis

so there is exactly one ``progress`` per completed step, the per-sub-question search
and embedding steps each appear **once per sub-question** (matching the decomposed
count), and the stream terminates with a single ``done`` event emitted **after** the
final ``synthesis`` progress. The ``step`` counter increments monotonically
``1..(2n + 2)`` across the whole run.
"""

from __future__ import annotations

import asyncio

import pytest

from ai_shared.sse import parse_sse_frame
from app.logic import (
    PHASE_DECOMPOSITION,
    PHASE_EMBEDDING,
    PHASE_SEARCH,
    PHASE_SYNTHESIS,
    research_sse,
)

from .conftest import (
    FakeCompleteClient,
    FakeEmbeddings,
    FakeSearch,
    FakeVectorStore,
    StubRepository,
    make_results,
    numbered_decomposition,
)


def _drain(gen) -> list[tuple[str, dict]]:
    """Run the async SSE generator to completion, parsing every frame."""
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


def _run_pipeline(n: int) -> list[tuple[str, dict]]:
    """Drive ``research_sse`` for a topic decomposed into ``n`` sub-questions."""
    # The LLM is called once for decomposition, then once per section at synthesis.
    client = FakeCompleteClient([numbered_decomposition(n)] + ["Section body."] * n)
    search = FakeSearch(default_results=make_results(2))
    embeddings = FakeEmbeddings()
    vector_store = FakeVectorStore()
    repo = StubRepository()

    frames = _drain(
        research_sse(
            "some research topic",
            client=client,
            search=search,
            embeddings=embeddings,
            vector_store=vector_store,
            repository=repo,
        )
    )
    # Sanity: every sub-question was searched once and stored once (deterministic run).
    assert len(search.calls) == n
    assert repo.saved  # the completed report was persisted (terminal done path)
    return frames


@pytest.mark.parametrize("n", [3, 4, 7, 10])
def test_progress_emitted_once_per_step_in_order(n: int) -> None:
    frames = _run_pipeline(n)

    # The expected ordered phase sequence: decomposition, then (search, embedding)
    # once per sub-question, then a single synthesis.
    expected_phases = (
        [PHASE_DECOMPOSITION]
        + [PHASE_SEARCH, PHASE_EMBEDDING] * n
        + [PHASE_SYNTHESIS]
    )

    progress = [data for (etype, data) in frames if etype == "progress"]
    actual_phases = [p["phase"] for p in progress]

    # Exactly one progress per completed step, in the correct order.
    assert actual_phases == expected_phases
    assert len(progress) == 2 * n + 2

    # The per-sub-question steps appear once per sub-question (matching the count).
    assert actual_phases.count(PHASE_SEARCH) == n
    assert actual_phases.count(PHASE_EMBEDDING) == n
    # The whole-run steps (decomposition, synthesis) appear exactly once.
    assert actual_phases.count(PHASE_DECOMPOSITION) == 1
    assert actual_phases.count(PHASE_SYNTHESIS) == 1

    # The step counter increments monotonically 1..(2n + 2) across the run.
    assert [p["step"] for p in progress] == list(range(1, 2 * n + 2 + 1))


@pytest.mark.parametrize("n", [3, 4, 7, 10])
def test_stream_terminates_with_done_after_final_synthesis(n: int) -> None:
    frames = _run_pipeline(n)
    types = [etype for (etype, _) in frames]

    # No terminal error on the happy path.
    assert "error" not in types

    # Exactly one terminal done, and it is the very last frame.
    assert types.count("done") == 1
    assert types[-1] == "done"

    # The done arrives strictly AFTER the final synthesis progress (the last
    # progress frame is the synthesis step).
    last_progress_index = max(i for i, (etype, _) in enumerate(frames) if etype == "progress")
    done_index = types.index("done")
    assert frames[last_progress_index][1]["phase"] == PHASE_SYNTHESIS
    assert done_index > last_progress_index

    # The done carries the completed report (a section per sub-question).
    done_data = frames[done_index][1]
    assert "report" in done_data
    assert len(done_data["report"]["sections"]) == n


def test_search_precedes_embedding_for_each_subquestion() -> None:
    """Within each sub-question, the search step is emitted before its embedding step.

    Guards the per-sub-question ordering (Requirement 7.6): the service searches the
    web for a sub-question, then stores that content as embeddings — so for every
    sub-question the ``search`` progress must immediately precede its ``embedding``
    progress, never the reverse.
    """
    n = 5
    frames = _run_pipeline(n)
    progress_phases = [data["phase"] for (etype, data) in frames if etype == "progress"]

    # Drop the leading decomposition and the trailing synthesis; what remains is the
    # per-sub-question (search, embedding) pairs.
    middle = progress_phases[1:-1]
    assert len(middle) == 2 * n
    pairs = [(middle[i], middle[i + 1]) for i in range(0, len(middle), 2)]
    assert pairs == [(PHASE_SEARCH, PHASE_EMBEDDING)] * n
