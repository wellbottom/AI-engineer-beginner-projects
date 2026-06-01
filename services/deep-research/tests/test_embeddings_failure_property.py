"""Property-based test: embeddings failure yields an identifying error (Property 18).

# Feature: ai-engineer-practice-monorepo, Property 18: any embeddings failure (research storage or capstone ingestion) yields an error identifying the embeddings/ingestion failure

**Validates: Requirements 7.7, 9.10**

For any simulated Embeddings_Service failure during Deep Research storage,
:func:`app.logic.research_sse` returns a terminal ``error`` frame that identifies
the embeddings failure (a non-empty reason, ``stage`` in
``{"embedding", "synthesis"}``). No completed report is produced and **nothing** is
persisted. The capstone-ingestion half of this property is validated in the
capstone service; here we cover the deep-research research-storage path, where the
embeddings failure can occur on any sub-question's embed-and-store step (or on the
synthesis-time retrieval embedding).

(The shared vector-store wrapper also surfaces Chroma failures as
:class:`EmbeddingsError`, so a vector-store ``add``/``query`` failure is covered by
the same identifying-error contract.)
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.sse import parse_sse_frame
from app.logic import ACTION, PHASE_EMBEDDING, PHASE_SYNTHESIS, research_sse

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
        "embeddings provider unavailable",
        "HF inference 503",
        "embeddings timed out",
        "",
    ]
)


# Feature: ai-engineer-practice-monorepo, Property 18: any embeddings failure (research storage or capstone ingestion) yields an error identifying the embeddings/ingestion failure
@settings(max_examples=150, deadline=None)
@given(
    n=st.integers(min_value=3, max_value=6),
    fail_call=st.integers(min_value=0, max_value=8),
    reason=_reasons,
)
def test_embeddings_failure_yields_identifying_error(n: int, fail_call: int, reason: str) -> None:
    # Each researched sub-question triggers exactly one embeddings.embed call (the
    # store step). Embed calls during research storage are indices 0..n-1; choosing
    # any of them forces a research-storage embeddings failure.
    fail_call = fail_call % n
    sub_texts = [f"Sub-question number {i}?" for i in range(1, n + 1)]
    decomposition = "\n".join(sub_texts)

    client = FakeCompleteClient([decomposition] + ["section body"] * n)
    search = FakeSearch(default_results=make_results(2))
    embeddings = FakeEmbeddings(raise_on={fail_call}, fail_reason=reason)
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

    # Exactly one terminal error frame identifying the embeddings failure.
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    err = errors[0]
    assert err["action"] == ACTION
    assert err["stage"] in (PHASE_EMBEDDING, PHASE_SYNTHESIS)
    assert isinstance(err["reason"], str) and err["reason"]  # identifies the failure

    # No completed report (no done) and nothing persisted.
    assert all(etype != "done" for (etype, _) in frames)
    assert repo.saved == []


# Feature: ai-engineer-practice-monorepo, Property 18: any embeddings failure (research storage or capstone ingestion) yields an error identifying the embeddings/ingestion failure
@settings(max_examples=120, deadline=None)
@given(n=st.integers(min_value=3, max_value=6), reason=_reasons)
def test_vector_store_add_failure_yields_identifying_error(n: int, reason: str) -> None:
    """A Vector_Store ``add`` failure is surfaced as an EmbeddingsError-identified error."""
    sub_texts = [f"Sub-question number {i}?" for i in range(1, n + 1)]
    decomposition = "\n".join(sub_texts)

    client = FakeCompleteClient([decomposition])
    search = FakeSearch(default_results=make_results(2))
    embeddings = FakeEmbeddings()
    vector_store = FakeVectorStore(raise_on_add=True, fail_reason=reason)
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

    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["stage"] == PHASE_EMBEDDING
    assert isinstance(errors[0]["reason"], str) and errors[0]["reason"]
    assert all(etype != "done" for (etype, _) in frames)
    assert repo.saved == []
