"""Core Support Chatbot assembly + streaming + persistence logic.

Framework-agnostic pieces of ``POST /chat`` so they are unit/property-testable
without spinning up FastAPI or a live gateway:

- :func:`assemble_messages` — build the LLM message list as the configured system
  prompt, then the retained conversation history (in order), then the new user
  message (Requirement 5.2, Property 7).
- :data:`OUT_OF_SCOPE_REPLY` — the single canned reply returned when a message is
  detected to fall outside the supported topics (Requirement 5.4).
- :func:`chat_sse` — an async generator that drives the turn: it runs the injectable
  out-of-scope classifier (Requirement 5.4), otherwise calls :meth:`LLMClient.stream`
  with this service's **30-second** timeout (Requirement 5.6), relays the reply as
  ``data`` frames (Requirement 5.5), persists the completed turn best-effort
  (Requirement 12.6), and emits a terminal ``done`` carrying the persistence
  indication (Requirement 12.4). On a gateway refusal/timeout it emits a terminal
  ``error`` stating the assistant is temporarily unavailable and **preserves** the
  existing conversation history (Requirement 5.6, Property 8).

History handling (Requirements 5.1, 5.4, 5.6):
- A *completed* turn (a normal LLM reply **or** the canned out-of-scope reply) is
  appended to the in-memory session via :class:`SessionStore` (50-turn cap) and
  persisted as a durable History_Record. The prior history is always retained.
- A *failed* turn (gateway refusal/timeout) appends nothing and persists nothing,
  so the post-call history is identical to the pre-call history (Property 8).
"""

from __future__ import annotations

from typing import AsyncIterator, Callable

from ai_shared.errors import LLMGatewayError, LLMTimeoutError
from ai_shared.history import ChatTurnResult, HistoryRepository, ProjectId, build_history_record
from ai_shared.llm_client import LLMClient
from ai_shared.llm_types import Message
from ai_shared.persistence import persist_record
from ai_shared.sse import format_data, format_done, format_error

from .classifier import Classifier
from .session_store import SessionStore, Turn

__all__ = [
    "assemble_messages",
    "chat_sse",
    "ACTION",
    "OUT_OF_SCOPE_REPLY",
    "TEMPORARILY_UNAVAILABLE",
    "CHAT_TIMEOUT_SECONDS",
]

#: Human-readable action label used on terminal ``error`` frames (Requirement 5.6).
ACTION = "chat"

#: This service's LLM timeout (Requirement 5.6: refuse/timeout within 30s).
CHAT_TIMEOUT_SECONDS = 30.0

#: The single canned reply for an out-of-scope message (Requirement 5.4).
OUT_OF_SCOPE_REPLY = (
    "I'm sorry, but that request is outside the topics I can help with. "
    "I can assist with questions about your account, billing and subscriptions, "
    "product features, setup and configuration, and troubleshooting."
)

#: Human-readable reason carried on the terminal ``error`` frame (Requirement 5.6).
TEMPORARILY_UNAVAILABLE = "The assistant is temporarily unavailable. Please try again shortly."


def assemble_messages(
    system_prompt: str,
    history: list[Turn],
    new_message: str,
) -> list[Message]:
    """Assemble the LLM message list (Requirement 5.2, Property 7).

    Returns the configured system prompt, followed by the retained conversation
    history expanded **in order** (each turn contributes its user message then its
    assistant reply), followed by the new user message. Pure function — no I/O.

    Args:
        system_prompt: The configured persona/topics system prompt.
        history: The retained conversation turns (oldest-first).
        new_message: The new (validated, trimmed) user message.

    Returns:
        The ordered ``list[Message]`` to send to the LLM_Client.
    """
    messages: list[Message] = [Message(role="system", content=system_prompt)]
    for turn in history:
        messages.append(Message(role="user", content=turn.user_message))
        messages.append(Message(role="assistant", content=turn.assistant_reply))
    messages.append(Message(role="user", content=new_message))
    return messages


def _persist_turn(
    repository: HistoryRepository,
    session_id: str,
    user_message: str,
    assistant_reply: str,
    operation_id_factory: Callable[[], str] | None,
):
    """Persist one completed turn best-effort; return the :class:`PersistenceOutcome`.

    Builds the ``ChatTurnResult`` -> ``ChatTurnRecord`` and writes it via the shared
    best-effort wrapper (Requirements 12.4, 12.6). Never raises for a persistence
    failure — the failure rides on the terminal ``done`` event.
    """
    result = ChatTurnResult(
        session_id=session_id,
        user_message=user_message,
        assistant_reply=assistant_reply,
    )
    record = build_history_record(ProjectId.SUPPORT, result)
    kwargs = {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    return persist_record(repository, ProjectId.SUPPORT, record, **kwargs)


async def chat_sse(
    session_id: str,
    message: str,
    *,
    store: SessionStore,
    client: LLMClient,
    repository: HistoryRepository,
    system_prompt: str,
    classifier: Classifier,
    operation_id_factory: Callable[[], str] | None = None,
) -> AsyncIterator[str]:
    """Stream one chat turn as SSE frames, persisting the completed turn.

    Flow (design "Service: Customer Support Chatbot"):

    1. Read the session's retained history (the pre-call history).
    2. If the injectable ``classifier`` detects the message is out of scope, stream
       the single canned :data:`OUT_OF_SCOPE_REPLY` as ``data``, append+persist the
       turn, and emit ``done`` — the LLM_Client is never called (Requirement 5.4).
    3. Otherwise assemble ``system + history + message`` (Requirement 5.2) and
       stream the reply via :meth:`LLMClient.stream` with a 30s timeout
       (Requirements 5.5, 5.6). On success append+persist the turn and emit
       ``done`` carrying the persistence indication.
    4. On a gateway refusal/timeout emit a terminal ``error`` (temporarily
       unavailable) and leave the history untouched (Requirement 5.6, Property 8).

    Args:
        session_id: The conversation's session id.
        message: The validated, trimmed user message.
        store: The in-memory :class:`SessionStore` (history read + append).
        client: The shared :class:`LLMClient`.
        repository: The shared :class:`HistoryRepository`.
        system_prompt: The configured system prompt (loaded once at startup).
        classifier: The injectable out-of-scope predicate (Requirement 5.4).
        operation_id_factory: Optional deterministic id factory for tests.
    """
    # (1) Pre-call retained history (creating the session if it is new/expired).
    session = store.get_or_create(session_id)
    pre_history = list(session.turns)

    # (2) Out-of-scope short-circuit: a single canned reply, no LLM call.
    if classifier(message, pre_history):
        yield format_data(OUT_OF_SCOPE_REPLY)
        store.append(session_id, Turn(user_message=message, assistant_reply=OUT_OF_SCOPE_REPLY))
        outcome = _persist_turn(
            repository, session_id, message, OUT_OF_SCOPE_REPLY, operation_id_factory
        )
        yield format_done(**outcome.attach_to_done({"out_of_scope": True}))
        return

    # (3) Normal path: assemble system + history + new message, then stream.
    messages = assemble_messages(system_prompt, pre_history, message)
    reply_parts: list[str] = []
    try:
        async for event in client.stream(messages, timeout=CHAT_TIMEOUT_SECONDS):
            if event.type == "data":
                text = event.data.get("text", "")
                if text:
                    reply_parts.append(text)
                    yield format_data(text)
            elif event.type == "done":
                # The client's terminal event marks completion; the service emits
                # its own terminal `done` (with the persistence indication) below.
                break
    except (LLMTimeoutError, LLMGatewayError):
        # (4) Gateway refusal/timeout: temporarily unavailable, history preserved.
        # Nothing is appended to the in-memory session and nothing is persisted, so
        # the post-call history is identical to the pre-call history (Property 8).
        yield format_error(ACTION, TEMPORARILY_UNAVAILABLE)
        return

    # Success: append the completed turn (50-turn cap) and persist best-effort.
    assistant_reply = "".join(reply_parts)
    store.append(session_id, Turn(user_message=message, assistant_reply=assistant_reply))
    outcome = _persist_turn(
        repository, session_id, message, assistant_reply, operation_id_factory
    )
    yield format_done(**outcome.attach_to_done())
