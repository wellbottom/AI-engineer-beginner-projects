"""Property-based test for conditional + capped RAG retrieval (Property 24).

# Feature: ai-engineer-practice-monorepo, Property 24: when retrieval is required, 1–5 chunks are included; when not required, none are retrieved or included

**Validates: Requirements 9.3**

For any agent step where retrieval is determined to be **required**, the number of
document chunks included in the LLM request is at least 1 and at most 5; and for any
step where retrieval is determined **not** to be required, no chunks are retrieved
and none are included. :func:`app.agent.perform_retrieval` is the function under
test, driven with an instrumented retriever that records whether it was called and
returns a generator-controlled number of candidate chunks.

The generator spans:
* required vs not-required retrieval steps,
* non-retrieval phases (which must never retrieve), and
* candidate counts of 0, 1, 5, 6, and larger (so the 5-cap is exercised on both
  sides of the boundary).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.agent import (
    MAX_RAG_CHUNKS,
    PHASE_ANSWER_SYNTHESIS,
    PHASE_PLANNING,
    PHASE_RETRIEVAL,
    PHASE_TOOL_INVOCATION,
    RetrievedChunk,
    StepDecision,
    perform_retrieval,
)


class _InstrumentedRetriever:
    """Records call count and returns ``candidate_count`` chunks when invoked."""

    def __init__(self, candidate_count: int) -> None:
        self._candidate_count = candidate_count
        self.calls = 0

    def __call__(self, decision: StepDecision) -> list[RetrievedChunk]:
        self.calls += 1
        return [
            RetrievedChunk(text=f"chunk {i}", source=f"doc-{i}.txt")
            for i in range(self._candidate_count)
        ]


_phases = st.sampled_from(
    [PHASE_RETRIEVAL, PHASE_PLANNING, PHASE_TOOL_INVOCATION, PHASE_ANSWER_SYNTHESIS]
)
# Candidate counts straddle the 5-cap boundary (0, 1, 5, 6) plus larger values.
_candidate_counts = st.one_of(
    st.sampled_from([0, 1, 4, 5, 6, 7]),
    st.integers(min_value=0, max_value=50),
)


# Feature: ai-engineer-practice-monorepo, Property 24: when retrieval is required, 1–5 chunks are included; when not required, none are retrieved or included
@settings(max_examples=300, deadline=None)
@given(phase=_phases, retrieval_required=st.booleans(), candidate_count=_candidate_counts)
def test_retrieval_is_conditional_and_capped(
    phase: str, retrieval_required: bool, candidate_count: int
) -> None:
    retriever = _InstrumentedRetriever(candidate_count)
    decision = StepDecision(phase=phase, query="some query", retrieval_required=retrieval_required)

    chunks = perform_retrieval(decision, retriever)

    required = phase == PHASE_RETRIEVAL and retrieval_required

    if not required:
        # Not required: the retriever was NEVER called and NO chunks are included
        # (Requirement 9.3 — the "retrieval not required" branch).
        assert retriever.calls == 0
        assert chunks == []
        return

    # Required: the retriever was called exactly once and the result is capped at 5.
    assert retriever.calls == 1
    assert len(chunks) == min(candidate_count, MAX_RAG_CHUNKS)
    assert len(chunks) <= MAX_RAG_CHUNKS

    if candidate_count >= 1:
        # When sources exist, at least 1 chunk is included (the "1–5" guarantee).
        assert 1 <= len(chunks) <= MAX_RAG_CHUNKS
    else:
        # A required retrieval that genuinely finds nothing yields no chunks (there
        # is nothing to include); the 1–5 guarantee applies when the store has hits.
        assert chunks == []


# Feature: ai-engineer-practice-monorepo, Property 24: when retrieval is required, 1–5 chunks are included; when not required, none are retrieved or included
@settings(max_examples=100, deadline=None)
@given(candidate_count=st.integers(min_value=6, max_value=100))
def test_required_retrieval_with_many_candidates_is_capped_at_5(candidate_count: int) -> None:
    """A required retrieval with >5 candidates always includes exactly 5 chunks."""
    retriever = _InstrumentedRetriever(candidate_count)
    decision = StepDecision(phase=PHASE_RETRIEVAL, query="q", retrieval_required=True)
    chunks = perform_retrieval(decision, retriever)
    assert len(chunks) == MAX_RAG_CHUNKS
    assert retriever.calls == 1
