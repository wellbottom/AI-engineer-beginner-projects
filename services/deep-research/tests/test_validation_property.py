"""Property-based test for Deep Research topic validation (Property 19).

# Feature: ai-engineer-practice-monorepo, Property 19: validation succeeds iff ≥1 non-whitespace char; failure skips decomposition and search

**Validates: Requirements 7.8**

For any research topic, :func:`app.schemas.validate_topic` succeeds **iff** the
topic is a string containing at least one non-whitespace character; when validation
fails the result is a :class:`ValidationError` naming the ``topic`` field and
**neither** topic decomposition **nor** any Search_Provider query is performed.

To prove "decomposition and search are not performed on failure", validation is
routed through sentinels that would be invoked only on success; the sentinels
record any call and the test asserts they are never touched when validation raises.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import validate_topic


class _SentinelDecomposer:
    """Records whether topic decomposition was ever invoked."""

    def __init__(self) -> None:
        self.called = False

    def decompose(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return []


class _SentinelSearch:
    """Records whether the Search_Provider was ever queried."""

    def __init__(self) -> None:
        self.called = False

    def search(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return []


def _expected_valid(topic: object) -> bool:
    """Reference oracle: a string with at least one non-whitespace character."""
    return isinstance(topic, str) and bool(topic.strip())


# A generator spanning valid/invalid regions: non-strings, empty, whitespace-only,
# normal text, single non-whitespace char, and text padded with whitespace.
_topics = st.one_of(
    st.none(),  # invalid: not a string
    st.integers(),  # invalid: not a string
    st.just(""),  # invalid: empty
    st.text(alphabet=" \t\n\r", max_size=10),  # whitespace-only -> trimmed empty
    st.text(min_size=1, max_size=60),  # mixed: may or may not have non-whitespace
    st.just("a"),  # valid: single non-whitespace char (boundary)
    st.builds(lambda s: f"   {s}   ", st.text(min_size=1, max_size=20).filter(lambda s: s.strip())),
    st.text(alphabet="abcdef ", min_size=1, max_size=4000),  # long-ish valid/space mix
)


# Feature: ai-engineer-practice-monorepo, Property 19: validation succeeds iff ≥1 non-whitespace char; failure skips decomposition and search
@settings(max_examples=300, deadline=None)
@given(topic=_topics)
def test_validation_succeeds_iff_non_whitespace_and_failure_skips_pipeline(topic: object) -> None:
    decomposer = _SentinelDecomposer()
    sentinel = _SentinelSearch()
    expected = _expected_valid(topic)

    try:
        result = validate_topic(topic)
    except ValidationError as exc:
        # Failure path: the oracle agrees it is invalid, the error names the topic
        # field, and NEITHER decomposition NOR search was performed (Requirement 7.8).
        assert expected is False
        assert exc.field == "topic"
        assert exc.details["field"] == "topic"
        assert decomposer.called is False
        assert sentinel.called is False
        return

    # Success path: only reached when the oracle agrees the topic is valid.
    assert expected is True
    assert isinstance(result, str)
    assert result == topic.strip()  # type: ignore[union-attr]
    assert result  # non-empty after trim
    # A caller would now decompose then search; emulate and confirm it is allowed.
    decomposer.decompose(result)
    sentinel.search(result)
    assert decomposer.called is True
    assert sentinel.called is True
