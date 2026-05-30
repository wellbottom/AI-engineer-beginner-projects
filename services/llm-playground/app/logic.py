"""Core LLM Playground generation + persistence logic (Requirements 4.3-4.6, 12.3-12.5).

This module holds the framework-agnostic pieces of ``POST /generate`` so they are
unit/property-testable without spinning up the FastAPI app or a live gateway:

- :func:`build_messages` — assemble the chat message list (optional system prompt
  followed by the user prompt).
- :func:`generate_sse` — an async generator that drives :meth:`LLMClient.stream`,
  relays each token chunk as a ``data`` SSE frame (Requirement 4.4), passes the
  validated ``temperature``/``max_tokens`` through to the client unchanged
  (Requirement 4.3), persists the completed run to the History_Store best-effort
  (Requirements 12.3-12.5), and emits a terminal ``done`` frame carrying the
  reported token usage (Requirement 4.6) plus the persistence indication
  (Requirement 12.4). If the gateway errors mid-stream it emits a terminal
  ``error`` frame including the gateway reason, even if a partial response was
  already produced (Requirement 4.5).

The persistence-failure indication rides on the terminal ``done`` event via
:meth:`ai_shared.persistence.PersistenceOutcome.attach_to_done`, so a persistence
failure never converts a successful stream into an ``error`` event (design
"History-write-failure policy").
"""

from __future__ import annotations

from typing import AsyncIterator, Callable

from ai_shared.errors import LLMGatewayError, LLMTimeoutError
from ai_shared.history import HistoryRepository, PlaygroundResult, ProjectId
from ai_shared.history import build_history_record
from ai_shared.llm_client import LLMClient, resolve_model
from ai_shared.llm_types import Message, Usage
from ai_shared.persistence import persist_record
from ai_shared.sse import format_data, format_done, format_error

from .schemas import PlaygroundRequest

__all__ = ["build_messages", "generate_sse", "ACTION"]

#: Human-readable action label used on error frames (Requirement 4.5).
ACTION = "generate"


def build_messages(request: PlaygroundRequest) -> list[Message]:
    """Build the chat message list for a playground request.

    The optional system prompt (when present and non-empty) precedes the user
    prompt. Returns a list of :class:`ai_shared.llm_types.Message`.
    """
    messages: list[Message] = []
    if request.system_prompt:
        messages.append(Message(role="system", content=request.system_prompt))
    messages.append(Message(role="user", content=request.prompt))
    return messages


def _usage_from_done(done_data: dict) -> Usage | None:
    """Extract a :class:`Usage` from the client's terminal ``done`` payload.

    The shared client emits ``done`` with ``data={"usage": {...}}`` when the gateway
    reported usage, or ``data={}`` otherwise. Returns ``None`` when no usage was
    reported so the terminal event omits the usage block (Requirement 4.6 applies
    only when usage is reported).
    """
    usage = done_data.get("usage")
    if not isinstance(usage, dict) or not usage:
        return None
    return Usage(
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
    )


async def generate_sse(
    request: PlaygroundRequest,
    client: LLMClient,
    repository: HistoryRepository,
    *,
    default_model: str,
    operation_id_factory: Callable[[], str] | None = None,
) -> AsyncIterator[str]:
    """Stream a playground generation as SSE frames and persist on completion.

    Yields ``data`` frames for each token chunk in order (Requirement 4.4), then a
    terminal ``done`` frame carrying the reported token usage (Requirement 4.6) and
    the persistence indication (Requirement 12.4). On a gateway timeout/error it
    yields a terminal ``error`` frame including the gateway reason (Requirement
    4.5) and persists nothing.

    Args:
        request: The validated request (its ``temperature``/``max_tokens`` are
            passed through to the client unchanged — Requirement 4.3).
        client: The shared :class:`LLMClient`.
        repository: The shared :class:`HistoryRepository` for the completed-run
            write (Requirement 12.5).
        default_model: The configured default model, used to resolve the model
            identifier persisted with the run.
        operation_id_factory: Optional override for the persistence-failure
            correlation id (deterministic tests).
    """
    messages = build_messages(request)

    response_parts: list[str] = []
    done_data: dict = {}

    try:
        async for event in client.stream(
            messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ):
            if event.type == "data":
                text = event.data.get("text", "")
                if text:
                    response_parts.append(text)
                    yield format_data(text)
            elif event.type == "done":
                # The client's terminal event signals completion; capture its
                # metadata (token usage) and stop relaying — the service emits its
                # own terminal `done` (with the persistence indication) below.
                done_data = dict(event.data)
                break
    except (LLMTimeoutError, LLMGatewayError) as exc:
        # Gateway timeout/error (possibly mid-stream, after partial content): emit
        # a terminal error including the gateway reason (Requirement 4.5). Nothing
        # is persisted for a failed run.
        yield format_error(ACTION, exc.reason)
        return

    # --- run completed: persist best-effort, then emit terminal `done` --------
    usage = _usage_from_done(done_data)
    result = PlaygroundResult(
        prompt=request.prompt,
        system_prompt=request.system_prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        model=resolve_model(request.model, default_model),
        response_text="".join(response_parts),
        usage=usage if usage is not None else Usage(0, 0, 0),
    )
    record = build_history_record(ProjectId.PLAYGROUND, result)

    kwargs = {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    outcome = persist_record(repository, ProjectId.PLAYGROUND, record, **kwargs)

    # Carry token usage (only when reported) plus the persistence indication on the
    # single terminal `done` event (Requirements 4.6, 12.4).
    done_payload = {"usage": usage.to_dict()} if usage is not None else {}
    done_payload = outcome.attach_to_done(done_payload)
    yield format_done(**done_payload)
