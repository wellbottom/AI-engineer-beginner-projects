"""Property-based test: step updates have valid phases + increasing positions (Property 27).

# Feature: ai-engineer-practice-monorepo, Property 27: every step update has a valid phase and the sequence positions are strictly increasing

**Validates: Requirements 9.7**

For any agent run, every streamed step update identifies a phase from {planning, tool
invocation, retrieval, answer synthesis} and the step sequence positions are strictly
increasing across the run. The async :func:`app.agent.run_task_sse` driver is run to
completion over an **injected** plan (deterministic, no live LLM/HF/Chroma) and every
``progress`` frame it emits is checked.

The generator spans plans of arbitrary phase sequences, both with and without a
terminal answer-synthesis step (so the no-answer / step-limit run is exercised too),
and includes tool/retrieval steps so all four phases appear.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.sse import parse_sse_frame
from app.agent import (
    PHASE_ANSWER_SYNTHESIS,
    PHASE_PLANNING,
    PHASE_RETRIEVAL,
    PHASE_TOOL_INVOCATION,
    VALID_PHASES,
    RetrievedChunk,
    StepDecision,
    run_task_sse,
)
from app.mcp import build_default_mcp_server

from .conftest import StubRepository

_BUILDABLE_PHASES = [PHASE_PLANNING, PHASE_TOOL_INVOCATION, PHASE_RETRIEVAL]


def _drain(gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


def _make_decision(phase: str) -> StepDecision:
    if phase == PHASE_TOOL_INVOCATION:
        return StepDecision(phase=phase, tool="word_count", arguments={"text": "x y"})
    if phase == PHASE_RETRIEVAL:
        return StepDecision(phase=phase, query="q", retrieval_required=True)
    return StepDecision(phase=PHASE_PLANNING)


_phase_lists = st.lists(st.sampled_from(_BUILDABLE_PHASES), min_size=0, max_size=30)


# Feature: ai-engineer-practice-monorepo, Property 27: every step update has a valid phase and the sequence positions are strictly increasing
@settings(max_examples=200, deadline=None)
@given(phases=_phase_lists, include_answer=st.booleans())
def test_every_step_update_has_valid_phase_and_strictly_increasing_positions(
    phases: list[str], include_answer: bool
) -> None:
    mcp_server = build_default_mcp_server()
    repo = StubRepository()

    decisions = [_make_decision(p) for p in phases]
    if include_answer:
        decisions.append(StepDecision(phase=PHASE_ANSWER_SYNTHESIS, answer="done"))

    frames = _drain(
        run_task_sse(
            "task text",
            mcp_server=mcp_server,
            retriever=lambda _d: [RetrievedChunk(text="t", source="doc.txt")],
            repository=repo,
            decisions=decisions,
        )
    )

    progress = [data for (etype, data) in frames if etype == "progress"]

    # Every step update identifies a VALID phase (Requirement 9.7).
    for update in progress:
        assert update["phase"] in VALID_PHASES

    # The sequence positions are strictly increasing across the run.
    positions = [update["step"] for update in progress]
    assert all(positions[i] < positions[i + 1] for i in range(len(positions) - 1))
    # Positions are exactly 1..N (one update per executed step, contiguous).
    assert positions == list(range(1, len(positions) + 1))

    # There is at most one terminal frame, and it is the last frame.
    types = [etype for (etype, _) in frames]
    assert types.count("done") + types.count("error") == 1
    assert types[-1] in ("done", "error")
