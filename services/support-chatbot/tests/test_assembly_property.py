"""Property-based test for the chatbot request assembly order (Property 7).

# Feature: ai-engineer-practice-monorepo, Property 7: the message list equals system prompt + retained history (in order) + new user message

**Validates: Requirements 5.2**

For any retained history and any valid user message, the message list produced by
:func:`app.logic.assemble_messages` equals the configured system prompt, followed by
the retained history expanded in order (each turn contributing its user message then
its assistant reply), followed by the new user message.

The test builds the expected list independently (an honest oracle) and asserts exact
structural equality: the first message is the system prompt, the trailing message is
the new user message, the middle is the history in order, and the roles alternate
user/assistant across the history block.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.llm_types import Message
from app.logic import assemble_messages
from app.session_store import Turn

_turns = st.builds(
    Turn,
    user_message=st.text(max_size=20),
    assistant_reply=st.text(max_size=20),
)


# Feature: ai-engineer-practice-monorepo, Property 7: the message list equals system prompt + retained history (in order) + new user message
@settings(max_examples=200, deadline=None)
@given(
    system_prompt=st.text(min_size=1, max_size=40),
    history=st.lists(_turns, max_size=50),
    new_message=st.text(min_size=1, max_size=40),
)
def test_message_list_equals_system_history_message(
    system_prompt: str, history: list[Turn], new_message: str
) -> None:
    messages = assemble_messages(system_prompt, history, new_message)

    # Build the expected sequence independently of the implementation.
    expected: list[Message] = [Message(role="system", content=system_prompt)]
    for turn in history:
        expected.append(Message(role="user", content=turn.user_message))
        expected.append(Message(role="assistant", content=turn.assistant_reply))
    expected.append(Message(role="user", content=new_message))

    assert messages == expected

    # Structural cross-checks.
    assert len(messages) == 2 + 2 * len(history)
    assert messages[0] == Message(role="system", content=system_prompt)
    assert messages[-1] == Message(role="user", content=new_message)
    # The history block (between system and the new message) alternates roles in
    # order: user, assistant, user, assistant, ...
    block = messages[1:-1]
    for idx, msg in enumerate(block):
        assert msg.role == ("user" if idx % 2 == 0 else "assistant")
    # And it reflects the history turns in order.
    for i, turn in enumerate(history):
        assert block[2 * i] == Message(role="user", content=turn.user_message)
        assert block[2 * i + 1] == Message(role="assistant", content=turn.assistant_reply)
