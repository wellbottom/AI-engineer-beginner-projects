"""Property-based test: gateway refusal/timeout preserves history (Property 8).

# Feature: ai-engineer-practice-monorepo, Property 8: any simulated refusal/timeout returns temporarily-unavailable and leaves history identical

**Validates: Requirements 5.6**

For any pre-call conversation history and any simulated gateway refusal or timeout,
:func:`app.logic.chat_sse` returns a terminal ``error`` stating the assistant is
temporarily unavailable and the post-call retained history is identical to the
pre-call history (nothing appended, nothing persisted).

The test seeds a :class:`SessionStore` with arbitrary pre-call turns, drives
``chat_sse`` with a :class:`FakeStreamClient` that raises either
:class:`LLMGatewayError` (refusal/unreachable) or :class:`LLMTimeoutError` (30s
timeout) — optionally after some partial chunks — and asserts the temporarily
unavailable error frame plus byte-for-byte history preservation and an empty
persistence stub.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import LLMGatewayError, LLMTimeoutError
from ai_shared.llm_types import StreamEvent
from ai_shared.sse import parse_sse_frame
from app.logic import TEMPORARILY_UNAVAILABLE, chat_sse
from app.session_store import SessionStore, Turn

from .conftest import FakeStreamClient, StubRepository

_turns = st.builds(
    Turn,
    user_message=st.text(max_size=15),
    assistant_reply=st.text(max_size=15),
)

# Each failure is (exception, partial-chunks-before-failure).
_failures = st.tuples(
    st.sampled_from(
        [LLMGatewayError(reason="connection refused"), LLMTimeoutError(reason="timed out after 30s")]
    ),
    st.lists(st.text(min_size=1, max_size=8), max_size=4),
)


def _always_in_scope(message: str, history: list[Turn]) -> bool:
    """Classifier stub: never out-of-scope, so the LLM path is always taken."""
    return False


def _drain(coro_gen) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []

    async def run() -> None:
        async for frame in coro_gen:
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())
    return frames


# Feature: ai-engineer-practice-monorepo, Property 8: any simulated refusal/timeout returns temporarily-unavailable and leaves history identical
@settings(max_examples=200, deadline=None)
@given(
    pre_turns=st.lists(_turns, max_size=8),
    message=st.text(min_size=1, max_size=20),
    failure=_failures,
)
def test_refusal_or_timeout_preserves_history(
    pre_turns: list[Turn], message: str, failure
) -> None:
    exc, partials = failure

    # Seed the store with the arbitrary pre-call history.
    store = SessionStore()
    session_id = store.create()
    for turn in pre_turns:
        store.append(session_id, turn)
    pre_history = list(store.get(session_id).turns)

    # A client that yields some partial chunks, then raises the gateway failure.
    events = [StreamEvent(type="data", data={"text": t}) for t in partials]
    client = FakeStreamClient(events, raise_exc=exc)
    repo = StubRepository()

    frames = _drain(
        chat_sse(
            session_id,
            message,
            store=store,
            client=client,
            repository=repo,
            system_prompt="system",
            classifier=_always_in_scope,
        )
    )

    # A terminal error frame stating temporarily unavailable (Requirement 5.6).
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == "chat"
    assert errors[0]["reason"] == TEMPORARILY_UNAVAILABLE
    # No terminal done event for a failed turn.
    assert all(etype != "done" for (etype, _) in frames)

    # Post-call history is identical to pre-call history (nothing appended).
    post_history = list(store.get(session_id).turns)
    assert post_history == pre_history
    # Nothing was persisted for a failed turn.
    assert repo.saved == []
