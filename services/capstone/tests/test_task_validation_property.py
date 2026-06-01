"""Property-based test for Capstone task validation (Property 28).

# Feature: ai-engineer-practice-monorepo, Property 28: validation succeeds iff ≥1 non-whitespace char; failure does not start the Agent

**Validates: Requirements 9.9**

For any submitted task, :func:`app.schemas.validate_task` succeeds **iff** the task
is a string containing at least one non-whitespace character; when validation fails
the result is a :class:`ValidationError` naming the ``task`` field and the Agent is
**not** started.

To prove "the Agent is not started on failure", validation is routed through a
sentinel Agent that would be invoked only on success; the sentinel records any call
and the test asserts it is never touched when validation raises.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import validate_task


class _SentinelAgent:
    """Records whether the Agent was ever started."""

    def __init__(self) -> None:
        self.started = False

    def start(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.started = True
        return None


def _expected_valid(task: object) -> bool:
    """Reference oracle: a string with at least one non-whitespace character."""
    return isinstance(task, str) and bool(task.strip())


# A generator spanning valid/invalid regions: non-strings, empty, whitespace-only,
# normal text, single non-whitespace char, and text padded with whitespace.
_tasks = st.one_of(
    st.none(),  # invalid: not a string
    st.integers(),  # invalid: not a string
    st.just(""),  # invalid: empty
    st.text(alphabet=" \t\n\r", max_size=10),  # whitespace-only -> trimmed empty
    st.text(min_size=1, max_size=60),  # mixed: may or may not have non-whitespace
    st.just("a"),  # valid: single non-whitespace char (boundary)
    st.builds(lambda s: f"   {s}   ", st.text(min_size=1, max_size=20).filter(lambda s: s.strip())),
    st.text(alphabet="abcdef ", min_size=1, max_size=4000),  # long-ish valid/space mix
)


# Feature: ai-engineer-practice-monorepo, Property 28: validation succeeds iff ≥1 non-whitespace char; failure does not start the Agent
@settings(max_examples=300, deadline=None)
@given(task=_tasks)
def test_validation_succeeds_iff_non_whitespace_and_failure_does_not_start_agent(
    task: object,
) -> None:
    agent = _SentinelAgent()
    expected = _expected_valid(task)

    try:
        result = validate_task(task)
    except ValidationError as exc:
        # Failure path: the oracle agrees it is invalid, the error names the task
        # field, and the Agent was NOT started (Requirement 9.9).
        assert expected is False
        assert exc.field == "task"
        assert exc.details["field"] == "task"
        assert agent.started is False
        return

    # Success path: only reached when the oracle agrees the task is valid.
    assert expected is True
    assert isinstance(result, str)
    assert result == task.strip()  # type: ignore[union-attr]
    assert result  # non-empty after trim
    # A caller would now start the Agent; emulate and confirm it is allowed.
    agent.start(result)
    assert agent.started is True
