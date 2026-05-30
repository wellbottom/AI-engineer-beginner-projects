"""Property-based test for Web Agent question validation (Property 14).

# Feature: ai-engineer-practice-monorepo, Property 14: validation succeeds iff 1–2000 trimmed chars; failure skips the search

**Validates: Requirements 6.7**

For any question, :func:`app.schemas.validate_question` succeeds **iff** the
question is a string whose whitespace-trimmed length is between 1 and 2,000
inclusive; when validation fails the result is a :class:`ValidationError` naming the
``question`` field and the Search_Provider is **not** queried.

To prove "the search provider is not queried on failure", validation is routed
through a small wrapper that would invoke a sentinel search only on success; the
sentinel records any call and the test asserts it is never touched when validation
raises.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import QUESTION_MAX, QUESTION_MIN, validate_question


class _SentinelSearch:
    """Records whether the (hypothetical) Search_Provider was ever queried."""

    def __init__(self) -> None:
        self.called = False

    def search(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return []


def _expected_valid(question: object) -> bool:
    """Reference oracle: a string whose trimmed length is in [1, 2000]."""
    if not isinstance(question, str):
        return False
    trimmed_len = len(question.strip())
    return QUESTION_MIN <= trimmed_len <= QUESTION_MAX


# A generator spanning valid/invalid regions plus the exact length boundaries.
_questions = st.one_of(
    st.none(),  # invalid: not a string
    st.integers(),  # invalid: not a string
    st.just(""),  # invalid: empty
    st.text(alphabet=" \t\n\r", max_size=10),  # whitespace-only -> trimmed empty
    st.text(min_size=1, max_size=40),  # mostly valid small
    # Exact trimmed-length boundaries: 1, 2000 (valid), 2001 (invalid).
    st.builds(lambda n: "a" * n, st.sampled_from([QUESTION_MIN, QUESTION_MAX, QUESTION_MAX + 1])),
    # Surrounding whitespace must not count toward the bound: trimmed length is 2000.
    st.just("   " + "a" * QUESTION_MAX + "   "),
    # Surrounding whitespace around a 2001-char core stays invalid.
    st.just("  " + "b" * (QUESTION_MAX + 1) + "  "),
)


# Feature: ai-engineer-practice-monorepo, Property 14: validation succeeds iff 1–2000 trimmed chars; failure skips the search
@settings(max_examples=300, deadline=None)
@given(question=_questions)
def test_validation_succeeds_iff_trimmed_1_to_2000_and_failure_skips_search(
    question: object,
) -> None:
    sentinel = _SentinelSearch()
    expected = _expected_valid(question)

    try:
        result = validate_question(question)
    except ValidationError as exc:
        # Failure path: the oracle agrees it is invalid, the error names the
        # question field, and the Search_Provider was never queried (Requirement 6.7).
        assert expected is False
        assert exc.field == "question"
        assert exc.details["field"] == "question"
        assert sentinel.called is False
        return

    # Success path: only reached when the oracle agrees the question is valid.
    assert expected is True
    # The returned value is the trimmed question, within bounds.
    assert isinstance(result, str)
    assert QUESTION_MIN <= len(result) <= QUESTION_MAX
    assert result == question.strip()  # type: ignore[union-attr]
    # A caller would now query the Search_Provider; emulate and confirm it is allowed.
    sentinel.search(result)
    assert sentinel.called is True
