"""Property-based test: final response reports invoked tools + sources (Property 26).

# Feature: ai-engineer-practice-monorepo, Property 26: the final response's tool list equals tools actually invoked (each flagged ok/failed) and sources equal documents actually referenced

**Validates: Requirements 9.6, 9.8**

For any completed agent run, the final response's list of invoked MCP tools equals
the set of tools the Agent actually invoked — each flagged with its success/failure
outcome so that every failed tool invocation appears marked as failed — and the list
of sources equals the documents the Agent actually referenced. The async
:func:`app.agent.run_task_sse` driver is run to completion over an **injected** plan
(deterministic, no live LLM/HF/Chroma), and its terminal ``done`` payload is checked
against an independent oracle computed from the same plan.

The generator builds plans mixing successful tool calls (``word_count``), failing
tool calls (``calculator`` with a non-arithmetic argument, and an unknown tool name),
and retrieval steps that reference specific source documents — so both the ok/failed
tool flags and the referenced-source set are exercised.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.sse import parse_sse_frame
from app.agent import (
    PHASE_ANSWER_SYNTHESIS,
    PHASE_RETRIEVAL,
    PHASE_TOOL_INVOCATION,
    RetrievedChunk,
    StepDecision,
    run_task_sse,
)
from app.mcp import build_default_mcp_server

from .conftest import StubRepository

# Each "tool op" is one of: a successful call, a failing call, or an unknown tool.
_TOOL_OK = "ok"
_TOOL_FAIL = "fail"
_TOOL_UNKNOWN = "unknown"
_tool_ops = st.lists(st.sampled_from([_TOOL_OK, _TOOL_FAIL, _TOOL_UNKNOWN]), min_size=0, max_size=8)
# A set of source document names a retrieval step references (possibly empty).
_source_sets = st.lists(st.text(min_size=1, max_size=10), min_size=0, max_size=5, unique=True)


def _drain(gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


def _tool_decision(op: str) -> tuple[StepDecision, tuple[str, bool]]:
    """Build a tool decision + the oracle (tool_name, ok) it should produce."""
    if op == _TOOL_OK:
        return (
            StepDecision(phase=PHASE_TOOL_INVOCATION, tool="word_count", arguments={"text": "a b c"}),
            ("word_count", True),
        )
    if op == _TOOL_FAIL:
        return (
            StepDecision(phase=PHASE_TOOL_INVOCATION, tool="calculator", arguments={"expression": "not math"}),
            ("calculator", False),
        )
    # unknown tool name -> recorded as a failed invocation under that name.
    return (
        StepDecision(phase=PHASE_TOOL_INVOCATION, tool="does_not_exist", arguments={}),
        ("does_not_exist", False),
    )


# Feature: ai-engineer-practice-monorepo, Property 26: the final response's tool list equals tools actually invoked (each flagged ok/failed) and sources equal documents actually referenced
@settings(max_examples=200, deadline=None)
@given(tool_ops=_tool_ops, sources=_source_sets)
def test_final_response_tools_and_sources_match_actual(
    tool_ops: list[str], sources: list[str]
) -> None:
    mcp_server = build_default_mcp_server()
    repo = StubRepository()

    decisions: list[StepDecision] = []
    expected_tools: list[tuple[str, bool]] = []
    for op in tool_ops:
        decision, expected = _tool_decision(op)
        decisions.append(decision)
        expected_tools.append(expected)

    # A retrieval step referencing the given source documents.
    chunks = [RetrievedChunk(text=f"text for {s}", source=s) for s in sources]
    decisions.append(StepDecision(phase=PHASE_RETRIEVAL, query="q", retrieval_required=True))
    decisions.append(StepDecision(phase=PHASE_ANSWER_SYNTHESIS, answer="the final answer"))

    frames = _drain(
        run_task_sse(
            "do the task",
            mcp_server=mcp_server,
            retriever=lambda _d: chunks,
            repository=repo,
            decisions=decisions,
        )
    )

    done = [data for (etype, data) in frames if etype == "done"]
    assert len(done) == 1
    payload = done[0]

    # Tools list equals the tools actually invoked, each flagged ok/failed (Req 9.6/9.8).
    actual_tools = [(t["tool"], t["ok"]) for t in payload["tools_invoked"]]
    assert actual_tools == expected_tools
    # Every failing op is present and marked failed (no failure is dropped — Req 9.8).
    for (name, ok), op in zip(actual_tools, tool_ops):
        assert ok == (op == _TOOL_OK)
        if op != _TOOL_OK:
            assert any((t["tool"] == name and t["ok"] is False) for t in payload["tools_invoked"])

    # Sources equal the documents actually referenced (distinct, first-seen order).
    expected_sources: list[str] = []
    for s in sources:
        if s not in expected_sources:
            expected_sources.append(s)
    assert payload["sources"] == expected_sources

    # The final answer is reported and the run completed (not step-limited).
    assert payload["answer"] == "the final answer"
    assert payload["step_limit_reached"] is False
    # The completed run was persisted (terminal done path).
    assert repo.saved
