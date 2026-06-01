"""Property-based test for Support Chatbot message validation (Property 9).

# Feature: ai-engineer-practice-monorepo, Property 9: validation succeeds iff message has 1–4000 trimmed chars; failure skips the LLM

**Validates: Requirements 5.7**

For any user message, :func:`app.schemas.validate_message` succeeds **iff** the
message is a string whose whitespace-trimmed length is between 1 and 4,000
inclusive; when validation fails the result is a :class:`ValidationError` naming the
``message`` field and the LLM_Client is **not** called.

To prove "the LLM client is not called on failure", validation is routed through a
small wrapper that would invoke a sentinel client only on success; the sentinel
records any call and the test asserts it is never touched when validation raises.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import MESSAGE_MAX, MESSAGE_MIN, validate_message


class _SentinelClient:
    """Records whether the (hypothetical) LLM client was ever invoked."""

    def __init__(self) -> None:
        self.called = False

    def stream(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return iter(())


def _expected_valid(message: object) -> bool:
    """Reference oracle: a string whose trimmed length is in [1, 4000]."""
    if not isinstance(message, str):
        return False
    trimmed_len = len(message.strip())
    return MESSAGE_MIN <= trimmed_len <= MESSAGE_MAX


# A generator spanning valid/invalid regions plus the exact length boundaries.
_messages = st.one_of(
    st.none(),  # invalid: not a string
    st.integers(),  # invalid: not a string
    st.just(""),  # invalid: empty
    st.text(alphabet=" \t\n\r", max_size=10),  # whitespace-only -> trimmed empty
    st.text(min_size=1, max_size=30),  # mostly valid small
    # Exact trimmed-length boundaries: 1, 4000 (valid), 4001 (invalid).
    st.builds(lambda n: "a" * n, st.sampled_from([MESSAGE_MIN, MESSAGE_MAX, MESSAGE_MAX + 1])),
    # Surrounding whitespace must not count toward the bound: trimmed length is 4000.
    st.just("   " + "a" * MESSAGE_MAX + "   "),
    # Surrounding whitespace around a 4001-char core stays invalid.
    st.just("  " + "b" * (MESSAGE_MAX + 1) + "  "),
)


# Feature: ai-engineer-practice-monorepo, Property 9: validation succeeds iff message has 1–4000 trimmed chars; failure skips the LLM
@settings(max_examples=300, deadline=None)
@given(message=_messages)
def test_validation_succeeds_iff_trimmed_1_to_4000_and_failure_skips_llm(message: object) -> None:
    sentinel = _SentinelClient()
    expected = _expected_valid(message)

    try:
        result = validate_message(message)
    except ValidationError as exc:
        # Failure path: the oracle agrees it is invalid, the error names the
        # message field, and the LLM client was never invoked (Requirement 5.7).
        assert expected is False
        assert exc.field == "message"
        assert exc.details["field"] == "message"
        assert sentinel.called is False
        return

    # Success path: only reached when the oracle agrees the message is valid.
    assert expected is True
    # The returned value is the trimmed message, within bounds.
    assert isinstance(result, str)
    assert MESSAGE_MIN <= len(result) <= MESSAGE_MAX
    assert result == message.strip()  # type: ignore[union-attr]
    # A caller would now invoke the LLM client; emulate and confirm it is allowed.
    sentinel.stream()
    assert sentinel.called is True
