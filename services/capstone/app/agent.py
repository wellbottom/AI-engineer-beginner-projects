"""Capstone Agent core: the bounded step loop, RAG wiring, and the task SSE driver.

This module holds the framework-agnostic Agent logic so it is unit/property-testable
without spinning up FastAPI, a live LLM_Gateway, a live HF embeddings client, a real
Chroma store, or a real Database. It implements the design's Agent + RAG behaviors
(Requirements 9.1, 9.3, 9.4, 9.6, 9.7, 9.8, 9.11) plus the task-run persistence
(Requirement 12.10).

Decision model
--------------
An Agent run is driven by a sequence of :class:`StepDecision` objects (the "plan").
Keeping the decisions **injected** makes the loop pure and the property tests
deterministic — no live LLM/HF/Chroma/network is needed. Each decision names the
phase to execute next:

- ``planning`` — a thinking step (no side effect).
- ``tool_invocation`` — invoke an MCP tool by name with arguments (:mod:`app.mcp`).
- ``retrieval`` — RAG: retrieve up to 5 chunks when ``retrieval_required`` is set.
- ``answer_synthesis`` — produce the final answer and stop the loop.

Pure functions
--------------
- :func:`invoke_tool` — invoke one MCP tool and map success/failure onto a
  :class:`ai_shared.history.ToolInvocation` (failures are recorded, never raised, so
  the Agent continues — Requirement 9.8).
- :func:`perform_retrieval` — the conditional + capped RAG step (Property 24): when a
  step requires retrieval, return **1–5** chunks (capped at 5); when retrieval is not
  required, return **none** and never call the retriever.
- :func:`agent_step_loop` — the **pure** bounded loop (Properties 23, 26, 27):
  executes **at most 25 steps**; stops as soon as an ``answer_synthesis`` decision is
  reached; when no decision ever produces a final answer it pads with ``planning``
  steps and stops at **exactly 25** flagged ``step_limit_reached`` with the gathered
  tool results + sources (Requirement 9.11).

Task SSE driver
---------------
- :func:`run_task_sse` — the async generator behind ``POST /task``. The handler has
  already validated the task (Requirement 9.9). It drives the same bounded loop while
  streaming one ``progress`` step update per phase (identifying the phase and the
  step's sequence position — Requirement 9.7), invoking MCP tools + RAG retrieval
  (Requirement 9.4), recording tool failures and continuing (Requirement 9.8), and on
  completion emitting a terminal ``done`` carrying the final answer + the list of MCP
  tools invoked (each flagged ok/failed) + the referenced source documents
  (Requirement 9.6) + the step-limit indication, plus the persistence indication
  (Requirements 12.10, 12.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterable, Sequence

from ai_shared.errors import EmbeddingsError, LLMGatewayError, LLMTimeoutError
from ai_shared.history import (
    CapstoneTaskResult,
    HistoryRepository,
    ProjectId,
    ToolInvocation,
    build_history_record,
)
from ai_shared.llm_client import LLMClient
from ai_shared.llm_types import Message
from ai_shared.persistence import persist_record
from ai_shared.sse import format_done, format_error, format_progress

from .mcp import MCPServer, MCPToolError

__all__ = [
    "PHASE_PLANNING",
    "PHASE_TOOL_INVOCATION",
    "PHASE_RETRIEVAL",
    "PHASE_ANSWER_SYNTHESIS",
    "VALID_PHASES",
    "MAX_STEPS",
    "MAX_RAG_CHUNKS",
    "ACTION",
    "StepDecision",
    "AgentStep",
    "RetrievedChunk",
    "AgentRunResult",
    "invoke_tool",
    "perform_retrieval",
    "agent_step_loop",
    "default_plan",
    "make_rag_retriever",
    "run_task_sse",
    "SYNTHESIS_SYSTEM_PROMPT",
]

#: The four agent phases streamed over SSE (Requirement 9.7).
PHASE_PLANNING = "planning"
PHASE_TOOL_INVOCATION = "tool_invocation"
PHASE_RETRIEVAL = "retrieval"
PHASE_ANSWER_SYNTHESIS = "answer_synthesis"

#: The set of valid phase identifiers (Property 27).
VALID_PHASES = frozenset(
    {PHASE_PLANNING, PHASE_TOOL_INVOCATION, PHASE_RETRIEVAL, PHASE_ANSWER_SYNTHESIS}
)

#: The maximum number of steps the Agent may execute (Requirements 9.1, 9.11).
MAX_STEPS = 25

#: The maximum number of RAG document chunks included in an LLM request (Req 9.3).
MAX_RAG_CHUNKS = 5

#: Human-readable action label used on terminal ``error`` frames.
ACTION = "run task"

#: System prompt for the final answer synthesis (Requirement 9.4/9.6).
SYNTHESIS_SYSTEM_PROMPT = (
    "You are a capable task-solving agent. Using the user's task together with any "
    "tool results and retrieved document context provided, produce a clear, accurate "
    "final answer. Base your answer on the supplied context and tool results; do not "
    "invent facts that are not supported by them."
)


@dataclass
class StepDecision:
    """One injected agent decision: the phase to execute and its parameters.

    Attributes:
        phase: One of :data:`VALID_PHASES`.
        detail: Human-readable description streamed in the ``progress`` update.
        tool: For ``tool_invocation`` — the MCP tool name to invoke.
        arguments: For ``tool_invocation`` — the tool arguments.
        query: For ``retrieval`` — the RAG query text.
        retrieval_required: For ``retrieval`` — whether retrieval is required. When
            ``False`` no chunks are retrieved or included (Requirement 9.3).
        answer: For ``answer_synthesis`` — a pre-computed final answer. ``None`` means
            the SSE driver synthesizes the answer via the LLM at execution time.
    """

    phase: str
    detail: str = ""
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    query: str | None = None
    retrieval_required: bool = True
    answer: str | None = None


@dataclass
class AgentStep:
    """One executed agent step (mirrors the design Data Model).

    ``index`` is the 1-based sequence position (Requirement 9.7); ``phase`` is one of
    :data:`VALID_PHASES`.
    """

    index: int
    phase: str
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "phase": self.phase, "detail": self.detail}


@dataclass
class RetrievedChunk:
    """One RAG chunk retrieved from the Vector_Store.

    ``text`` is the chunk content included in the LLM request; ``source`` is the
    document name the chunk came from (the "referenced source", Requirement 9.6).
    """

    text: str
    source: str


@dataclass
class AgentRunResult:
    """The outcome of an Agent run (Requirements 9.6, 9.11).

    Attributes:
        answer: The final answer (empty when the step limit was reached with none).
        steps: The executed steps, in order (1-based ``index``).
        tools_invoked: Every MCP tool invocation with its ok/failed outcome.
        sources: The distinct document names the Agent referenced (in first-seen order).
        step_limit_reached: ``True`` iff the run stopped at the 25-step limit without
            producing a final answer.
        retrieved_context: The retrieved chunk texts (fed to answer synthesis).
    """

    answer: str
    steps: list[AgentStep]
    tools_invoked: list[ToolInvocation]
    sources: list[str]
    step_limit_reached: bool
    retrieved_context: list[str] = field(default_factory=list)


def invoke_tool(mcp_server: MCPServer, decision: StepDecision) -> ToolInvocation:
    """Invoke one MCP tool and record the ok/failed outcome (Requirement 9.8).

    Pure with respect to the (injected) ``mcp_server``: a tool that succeeds yields
    ``ToolInvocation(tool, ok=True, error=None)``; an unknown tool or one that raises
    yields ``ToolInvocation(tool, ok=False, error=reason)``. It **never** raises, so
    the Agent records the failed tool and continues with the remaining steps.

    Args:
        mcp_server: The MCP_Server exposing the tools.
        decision: A ``tool_invocation`` decision naming the ``tool`` + ``arguments``.

    Returns:
        The :class:`ai_shared.history.ToolInvocation` recording the outcome.
    """
    name = decision.tool or ""
    try:
        mcp_server.invoke(name, decision.arguments or {})
        return ToolInvocation(tool=name, ok=True, error=None)
    except MCPToolError as exc:
        return ToolInvocation(tool=exc.tool, ok=False, error=exc.reason)


def perform_retrieval(
    decision: StepDecision,
    retriever: Callable[[StepDecision], Iterable[RetrievedChunk]] | None,
) -> list[RetrievedChunk]:
    """Perform conditional, capped RAG retrieval for one step (Property 24).

    When ``decision`` is a ``retrieval`` step **and** ``retrieval_required`` is set,
    the ``retriever`` is queried and the result is capped at :data:`MAX_RAG_CHUNKS`
    (5) — so **1–5** chunks are included whenever the retriever returns ≥1. When the
    step does not require retrieval (a non-retrieval phase, or ``retrieval_required``
    is ``False``), the retriever is **never called** and **no** chunks are returned
    (Requirement 9.3).

    Args:
        decision: The current step decision.
        retriever: A callable mapping a retrieval decision to candidate chunks (the
            Vector_Store query), or ``None``.

    Returns:
        The 0 (not required) or 1–5 (required) :class:`RetrievedChunk` objects to
        include in the LLM request.

    Raises:
        EmbeddingsError: Propagated from the retriever (embeddings/vector-store
            failure) so the caller can surface it (Requirement 9.10-style).
    """
    if decision.phase != PHASE_RETRIEVAL or not decision.retrieval_required:
        return []
    if retriever is None:
        return []
    chunks = list(retriever(decision))
    return chunks[:MAX_RAG_CHUNKS]


def _next_decision(decisions: Sequence[StepDecision], index: int) -> StepDecision:
    """Return the decision at ``index``, or an implicit ``planning`` step past the end.

    Once the injected plan is exhausted without a final answer, the Agent keeps
    "thinking" (a ``planning`` step) each step until it reaches the 25-step limit —
    this is what makes a no-answer run stop at exactly 25 (Requirement 9.11).
    """
    if index < len(decisions):
        return decisions[index]
    return StepDecision(phase=PHASE_PLANNING, detail="Continue planning.")


def agent_step_loop(
    decisions: Iterable[StepDecision],
    *,
    mcp_server: MCPServer,
    retriever: Callable[[StepDecision], Iterable[RetrievedChunk]] | None = None,
    max_steps: int = MAX_STEPS,
) -> AgentRunResult:
    """Execute the bounded agent loop over injected decisions (pure).

    The loop executes **at most** ``max_steps`` (25) steps. It stops as soon as an
    ``answer_synthesis`` decision is reached (using that decision's ``answer``). If no
    decision within the bound produces a final answer, the loop pads with ``planning``
    steps and stops at **exactly** ``max_steps`` with ``step_limit_reached=True``,
    returning the tool results and sources gathered so far (Requirements 9.1, 9.11).

    Tool invocations are recorded with their ok/failed outcome and never halt the loop
    (Requirement 9.8); retrieval is conditional and capped to 5 chunks (Requirement
    9.3); referenced source documents are accumulated in first-seen order
    (Requirement 9.6).

    Args:
        decisions: The injected plan (a sequence of :class:`StepDecision`).
        mcp_server: The MCP_Server exposing tools to the Agent.
        retriever: Optional RAG retriever (see :func:`perform_retrieval`).
        max_steps: The step bound (defaults to :data:`MAX_STEPS`).

    Returns:
        The :class:`AgentRunResult`.
    """
    decisions = list(decisions)
    steps: list[AgentStep] = []
    tools_invoked: list[ToolInvocation] = []
    sources: list[str] = []
    context: list[str] = []
    final_answer: str | None = None
    step_limit_reached = False

    for i in range(max_steps):
        decision = _next_decision(decisions, i)
        position = i + 1
        steps.append(AgentStep(index=position, phase=decision.phase, detail=decision.detail))

        if decision.phase == PHASE_TOOL_INVOCATION:
            tools_invoked.append(invoke_tool(mcp_server, decision))
        elif decision.phase == PHASE_RETRIEVAL:
            for chunk in perform_retrieval(decision, retriever):
                context.append(chunk.text)
                if chunk.source and chunk.source not in sources:
                    sources.append(chunk.source)
        elif decision.phase == PHASE_ANSWER_SYNTHESIS:
            final_answer = decision.answer if decision.answer is not None else ""
            break
        # planning (and any unrecognized phase) is a no-op thinking step.
    else:
        # The loop ran the full bound without reaching an answer_synthesis decision.
        step_limit_reached = True

    if final_answer is None:
        final_answer = ""
        step_limit_reached = True

    return AgentRunResult(
        answer=final_answer,
        steps=steps,
        tools_invoked=tools_invoked,
        sources=sources,
        step_limit_reached=step_limit_reached,
        retrieved_context=context,
    )


def default_plan(
    task: str,
    *,
    mcp_server: MCPServer,
    retriever: Callable[[StepDecision], Iterable[RetrievedChunk]] | None,
) -> list[StepDecision]:
    """Build a default deterministic plan ending in answer synthesis.

    Produces a small, reasonable plan that exercises the Agent's capabilities
    (Requirement 9.4): a planning step, one MCP tool invocation (the first registered
    tool, applied to the task), a RAG retrieval step (required only when a retriever
    is wired so retrieval is genuinely available — otherwise ``retrieval_required`` is
    ``False`` so no chunks are retrieved, Requirement 9.3), and a final
    ``answer_synthesis`` step whose ``answer`` is ``None`` so the SSE driver
    synthesizes it via the LLM.
    """
    tool_names = mcp_server.tool_names()
    plan: list[StepDecision] = [
        StepDecision(phase=PHASE_PLANNING, detail="Plan how to approach the task."),
    ]
    if tool_names:
        first = tool_names[0]
        plan.append(
            StepDecision(
                phase=PHASE_TOOL_INVOCATION,
                detail=f"Invoke the {first} tool.",
                tool=first,
                arguments={"text": task, "task": task},
            )
        )
    plan.append(
        StepDecision(
            phase=PHASE_RETRIEVAL,
            detail="Retrieve relevant document chunks.",
            query=task,
            retrieval_required=retriever is not None,
        )
    )
    plan.append(
        StepDecision(
            phase=PHASE_ANSWER_SYNTHESIS,
            detail="Synthesize the final answer.",
            answer=None,
        )
    )
    return plan


def make_rag_retriever(
    *,
    embeddings: Any,
    vector_store: Any,
    collection: str,
    top_k: int = MAX_RAG_CHUNKS,
) -> Callable[[StepDecision], list[RetrievedChunk]]:
    """Build a RAG retriever bound to the Embeddings_Service + Vector_Store (Req 9.3).

    The returned callable embeds the decision's ``query`` via the Embeddings_Service
    and queries the Vector_Store (Chroma) for up to ``top_k`` nearest chunks, mapping
    each hit onto a :class:`RetrievedChunk` (``text`` = the chunk document text,
    ``source`` = the chunk's ``doc_name`` metadata, falling back to ``source_url`` or
    the chunk id). An :class:`ai_shared.errors.EmbeddingsError` from either provider
    propagates to the caller.
    """

    def _retrieve(decision: StepDecision) -> list[RetrievedChunk]:
        query = decision.query or ""
        if not query.strip():
            return []
        vector = embeddings.embed_one(query)
        hits = vector_store.query(collection, vector, top_k=top_k)
        chunks: list[RetrievedChunk] = []
        for hit in hits:
            metadata = getattr(hit, "metadata", {}) or {}
            source = (
                metadata.get("doc_name")
                or metadata.get("source_url")
                or getattr(hit, "id", "")
            )
            chunks.append(
                RetrievedChunk(text=getattr(hit, "document_text", "") or "", source=source or "")
            )
        return chunks

    return _retrieve


def _synthesis_messages(
    task: str,
    context: Sequence[str],
    tools_invoked: Sequence[ToolInvocation],
) -> list[Message]:
    """Assemble the LLM message list for the final answer synthesis."""
    lines = [f"Task: {task}", ""]
    if tools_invoked:
        lines.append("Tool results:")
        for inv in tools_invoked:
            status = "ok" if inv.ok else f"failed ({inv.error})"
            lines.append(f"- {inv.tool}: {status}")
        lines.append("")
    if context:
        lines.append("Retrieved document context:")
        for index, text in enumerate(context, start=1):
            lines.append(f"[{index}] {text}")
        lines.append("")
    else:
        lines.append("(no document context was retrieved)")
    user_content = "\n".join(lines).rstrip()
    return [
        Message(role="system", content=SYNTHESIS_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]


async def _synthesize_answer(
    task: str,
    context: Sequence[str],
    tools_invoked: Sequence[ToolInvocation],
    *,
    synthesize: Callable[..., Any] | None,
    client: LLMClient | None,
    timeout: float,
) -> str:
    """Produce the final answer via the injected ``synthesize`` or the LLM_Client.

    Precedence: an injected ``synthesize`` callable (sync or async) is used first
    (deterministic tests); otherwise the LLM_Client synthesizes from the task + tool
    results + retrieved context; if neither is available, a deterministic fallback
    summary is returned.
    """
    if synthesize is not None:
        result = synthesize(task, list(context), list(tools_invoked))
        if hasattr(result, "__await__"):
            return await result
        return result
    if client is not None:
        completion = await client.complete(
            _synthesis_messages(task, context, tools_invoked), timeout=timeout
        )
        return completion.content
    # Deterministic fallback (no LLM configured): summarize what was gathered.
    if context:
        return f"Based on {len(context)} retrieved source(s): " + " ".join(context)
    return f"Completed the task: {task}"


def _gathered_summary(
    tools_invoked: Sequence[ToolInvocation], sources: Sequence[str]
) -> str:
    """Build the gathered-results summary returned when the step limit is reached."""
    return (
        f"The agent reached the {MAX_STEPS}-step limit without producing a final "
        f"answer. Gathered {len(tools_invoked)} tool result(s) and "
        f"{len(sources)} referenced source(s) so far."
    )


async def run_task_sse(
    task: str,
    *,
    mcp_server: MCPServer,
    retriever: Callable[[StepDecision], Iterable[RetrievedChunk]] | None,
    repository: HistoryRepository,
    decisions: Sequence[StepDecision] | None = None,
    plan: Callable[[str], Sequence[StepDecision]] | None = None,
    synthesize: Callable[..., Any] | None = None,
    client: LLMClient | None = None,
    operation_id_factory: Callable[[], str] | None = None,
    max_steps: int = MAX_STEPS,
    synthesis_timeout: float = 60.0,
) -> AsyncIterator[str]:
    """Stream one task run as SSE frames (Requirements 9.4, 9.6, 9.7, 9.8, 9.11, 12.10).

    The handler has already validated the task (Requirement 9.9). This drives the
    bounded agent loop while streaming one ``progress`` update per executed step
    (identifying the phase + sequence position, Requirement 9.7), invoking MCP tools
    and RAG retrieval (Requirement 9.4), recording tool failures and continuing
    (Requirement 9.8). On completion it persists the task History_Record
    (Requirement 12.10) and emits a terminal ``done`` carrying the final answer, the
    list of invoked tools (each flagged ok/failed), the referenced sources, the
    step-limit indication, and the persistence indication (Requirements 9.6, 12.4).

    A retrieval (embeddings/vector-store) failure emits a terminal ``error``
    (``stage: "retrieval"``); a synthesis gateway failure/timeout emits a terminal
    ``error`` (``stage: "answer_synthesis"``); neither persists a record.

    Args:
        task: The validated, trimmed task text.
        mcp_server: The MCP_Server exposing tools to the Agent.
        retriever: The RAG retriever (see :func:`make_rag_retriever`), or ``None``.
        repository: The shared :class:`HistoryRepository`.
        decisions: An explicit injected plan (for deterministic tests). When ``None``,
            ``plan`` (or :func:`default_plan`) builds the plan.
        plan: A callable building the plan from the task. Defaults to
            :func:`default_plan`.
        synthesize: Optional injected answer synthesizer (deterministic tests).
        client: The shared :class:`LLMClient` used for answer synthesis when no
            ``synthesize`` is injected.
        operation_id_factory: Optional deterministic id factory for tests.
        max_steps: The step bound (defaults to :data:`MAX_STEPS`).
        synthesis_timeout: Timeout for the synthesis LLM call.
    """
    if decisions is not None:
        plan_list = list(decisions)
    elif plan is not None:
        plan_list = list(plan(task))
    else:
        plan_list = default_plan(task, mcp_server=mcp_server, retriever=retriever)

    tools_invoked: list[ToolInvocation] = []
    sources: list[str] = []
    context: list[str] = []
    final_answer: str | None = None
    step_limit_reached = False

    for i in range(max_steps):
        decision = _next_decision(plan_list, i)
        position = i + 1

        if decision.phase == PHASE_TOOL_INVOCATION:
            inv = invoke_tool(mcp_server, decision)
            tools_invoked.append(inv)
            yield format_progress(
                PHASE_TOOL_INVOCATION,
                position,
                detail=decision.detail or f"Invoked the {inv.tool} tool.",
                tool=inv.tool,
                ok=inv.ok,
            )
        elif decision.phase == PHASE_RETRIEVAL:
            try:
                chunks = perform_retrieval(decision, retriever)
            except EmbeddingsError as exc:
                yield format_error(ACTION, exc.reason, stage=PHASE_RETRIEVAL)
                return
            for chunk in chunks:
                context.append(chunk.text)
                if chunk.source and chunk.source not in sources:
                    sources.append(chunk.source)
            yield format_progress(
                PHASE_RETRIEVAL,
                position,
                detail=decision.detail or "Retrieved relevant document chunks.",
                chunks=len(chunks),
            )
        elif decision.phase == PHASE_ANSWER_SYNTHESIS:
            yield format_progress(
                PHASE_ANSWER_SYNTHESIS,
                position,
                detail=decision.detail or "Synthesized the final answer.",
            )
            if decision.answer is not None:
                final_answer = decision.answer
            else:
                try:
                    final_answer = await _synthesize_answer(
                        task,
                        context,
                        tools_invoked,
                        synthesize=synthesize,
                        client=client,
                        timeout=synthesis_timeout,
                    )
                except (LLMTimeoutError, LLMGatewayError) as exc:
                    yield format_error(ACTION, exc.reason, stage=PHASE_ANSWER_SYNTHESIS)
                    return
            break
        else:
            # planning (and any unrecognized phase) is a thinking step.
            yield format_progress(
                PHASE_PLANNING,
                position,
                detail=decision.detail or "Planned the next step.",
            )
    else:
        step_limit_reached = True

    if final_answer is None:
        # Reached the step limit without a final answer (Requirement 9.11): return the
        # gathered results with the step-limit indication.
        final_answer = _gathered_summary(tools_invoked, sources)
        step_limit_reached = True

    # Persist the completed task run best-effort (Requirements 12.10, 12.4).
    result = CapstoneTaskResult(
        task_text=task,
        final_answer=final_answer,
        tools_invoked=tools_invoked,
        sources=sources,
        step_limit_reached=step_limit_reached,
    )
    record = build_history_record(ProjectId.CAPSTONE, result)
    kwargs = (
        {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    )
    outcome = persist_record(repository, ProjectId.CAPSTONE, record, **kwargs)

    done_payload = {
        "answer": final_answer,
        "tools_invoked": [t.to_json() for t in tools_invoked],
        "sources": list(sources),
        "step_limit_reached": step_limit_reached,
    }
    yield format_done(**outcome.attach_to_done(done_payload))
