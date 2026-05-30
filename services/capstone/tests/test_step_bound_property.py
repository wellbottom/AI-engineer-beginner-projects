"""Property-based test for the Capstone Agent's 25-step bound (Property 23).

# Feature: ai-engineer-practice-monorepo, Property 23: executed steps never exceed 25; a no-answer run stops at exactly 25 flagged as step-limit-reached with gathered results

**Validates: Requirements 9.1, 9.11**

For any agent run, the number of executed steps never exceeds 25; and for any run
that never produces a final answer, execution stops at **exactly 25** steps and the
result is flagged ``step_limit_reached`` while returning the results gathered so far
(tool invocations + referenced sources). :func:`app.agent.agent_step_loop` is the
pure loop under test, driven by **injected** :class:`app.agent.StepDecision` plans so
the run is fully deterministic (no live LLM/HF/Chroma).

The generator spans plans that:
* contain an ``answer_synthesis`` decision (the run should stop at that step), and
* never contain one (the run should pad to exactly 25 and flag the step limit),
including plans longer and shorter than the bound and the exact boundaries.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.agent import (
    MAX_STEPS,
    PHASE_ANSWER_SYNTHESIS,
    PHASE_PLANNING,
    PHASE_RETRIEVAL,
    PHASE_TOOL_INVOCATION,
    RetrievedChunk,
    StepDecision,
    agent_step_loop,
)
from app.mcp import build_default_mcp_server

# Non-terminal phases the generator can emit (none of these end the run).
_NON_TERMINAL = [PHASE_PLANNING, PHASE_TOOL_INVOCATION, PHASE_RETRIEVAL]


def _make_decision(phase: str) -> StepDecision:
    """Build a runnable :class:`StepDecision` for ``phase`` (tools resolve to a real tool)."""
    if phase == PHASE_TOOL_INVOCATION:
        return StepDecision(phase=phase, tool="word_count", arguments={"text": "hello world"})
    if phase == PHASE_RETRIEVAL:
        return StepDecision(phase=phase, query="q", retrieval_required=True)
    if phase == PHASE_ANSWER_SYNTHESIS:
        return StepDecision(phase=phase, answer="final answer")
    return StepDecision(phase=PHASE_PLANNING)


# A plan is a list of non-terminal phases optionally followed by a terminal one.
_non_terminal_phases = st.lists(st.sampled_from(_NON_TERMINAL), min_size=0, max_size=40)
_has_terminal = st.booleans()


def _retriever(_decision):
    """A deterministic retriever returning 2 chunks (so retrieval steps gather sources)."""
    return [
        RetrievedChunk(text="chunk a", source="doc-a.txt"),
        RetrievedChunk(text="chunk b", source="doc-b.txt"),
    ]


# Feature: ai-engineer-practice-monorepo, Property 23: executed steps never exceed 25; a no-answer run stops at exactly 25 flagged as step-limit-reached with gathered results
@settings(max_examples=200, deadline=None)
@given(non_terminal=_non_terminal_phases, has_terminal=_has_terminal, term_pos=st.integers(min_value=0, max_value=40))
def test_executed_steps_never_exceed_25_and_no_answer_stops_at_exactly_25(
    non_terminal: list[str], has_terminal: bool, term_pos: int
) -> None:
    mcp_server = build_default_mcp_server()

    # Build the plan: the non-terminal phases, optionally with a terminal
    # answer_synthesis spliced in at term_pos (clamped into range).
    phases = list(non_terminal)
    terminal_index: int | None = None
    if has_terminal:
        pos = term_pos % (len(phases) + 1)
        phases.insert(pos, PHASE_ANSWER_SYNTHESIS)
        terminal_index = pos

    decisions = [_make_decision(p) for p in phases]
    result = agent_step_loop(decisions, mcp_server=mcp_server, retriever=_retriever)

    # (A) The number of executed steps NEVER exceeds 25 (Requirement 9.1).
    assert len(result.steps) <= MAX_STEPS
    # Step indices are 1..len, strictly increasing.
    assert [s.index for s in result.steps] == list(range(1, len(result.steps) + 1))

    # Does an answer_synthesis decision occur within the executed bound?
    answer_within_bound = terminal_index is not None and terminal_index < MAX_STEPS

    if answer_within_bound:
        # The run stops AT the answer step (Requirement 9.6 completion).
        assert result.step_limit_reached is False
        assert len(result.steps) == terminal_index + 1
        assert result.steps[-1].phase == PHASE_ANSWER_SYNTHESIS
        assert result.answer == "final answer"
    else:
        # No answer within the bound: stop at EXACTLY 25, flagged step-limit-reached,
        # returning the gathered results so far (Requirement 9.11).
        assert len(result.steps) == MAX_STEPS
        assert result.step_limit_reached is True
        assert result.answer == ""
        # Gathered results are present: any tool/retrieval steps within the bound
        # contributed invocations/sources.
        executed_phases = [s.phase for s in result.steps]
        assert len(result.tools_invoked) == executed_phases.count(PHASE_TOOL_INVOCATION)
        if PHASE_RETRIEVAL in executed_phases:
            assert result.sources == ["doc-a.txt", "doc-b.txt"]


# Feature: ai-engineer-practice-monorepo, Property 23: executed steps never exceed 25; a no-answer run stops at exactly 25 flagged as step-limit-reached with gathered results
@settings(max_examples=100, deadline=None)
@given(plan_len=st.integers(min_value=0, max_value=60))
def test_plan_without_answer_always_stops_at_exactly_25(plan_len: int) -> None:
    """A plan of only non-terminal steps always runs to exactly 25 and flags the limit."""
    mcp_server = build_default_mcp_server()
    decisions = [StepDecision(phase=PHASE_PLANNING) for _ in range(plan_len)]
    result = agent_step_loop(decisions, mcp_server=mcp_server)
    assert len(result.steps) == MAX_STEPS
    assert result.step_limit_reached is True
    assert result.answer == ""
