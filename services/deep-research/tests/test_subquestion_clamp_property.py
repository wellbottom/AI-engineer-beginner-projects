"""Property-based test for the Deep Research sub-question clamp (Property 15).

# Feature: ai-engineer-practice-monorepo, Property 15: the number of sub-questions used is always between 3 and 10

**Validates: Requirements 7.1**

For any raw topic decomposition produced by the LLM, the number of sub-questions
actually *used* is at least 3 and at most 10. :func:`app.logic.clamp_subquestions`
normalizes the raw list (trim, drop blank/whitespace-only entries, de-duplicate
preserving first-seen order) and then:

* ``> 10`` distinct → truncates to the first 10 → returned length is exactly 10 and
  is an order-preserving prefix of the distinct inputs;
* ``3..10`` distinct → returned unchanged;
* ``< 3`` distinct → raises :class:`LLMGatewayError` (a decomposition failure — no
  sub-questions are used, so the [3, 10] invariant is never violated; see BUG-008).

The generator spans all three regions plus the exact count boundaries (2, 3, 10,
11) and deliberately injects blanks/whitespace and duplicates so the normalization
and clamp are exercised together.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import LLMGatewayError
from app.logic import MAX_SUBQUESTIONS, MIN_SUBQUESTIONS, clamp_subquestions


def _distinct_count(raw: list) -> int:
    """Reference oracle: count distinct, non-blank, trimmed string entries."""
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
    return len(seen)


def _distinct_in_order(raw: list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            out.append(trimmed)
    return out


# Candidate sub-question entries: distinct cores, blanks, whitespace, duplicates.
_entry = st.one_of(
    st.text(min_size=1, max_size=12).filter(lambda s: s.strip()),
    st.just(""),
    st.text(alphabet=" \t\n", min_size=1, max_size=4),  # whitespace-only -> dropped
)

# Raw lists spanning 0..14 entries (so post-normalization count straddles 3 and 10).
_raw_lists = st.lists(_entry, min_size=0, max_size=14)

# Lists guaranteed to have a controlled number of DISTINCT entries via unique cores.
_unique_cores = st.integers(min_value=0, max_value=14).map(
    lambda k: [f"distinct-sub-question-{i}" for i in range(k)]
)


# Feature: ai-engineer-practice-monorepo, Property 15: the number of sub-questions used is always between 3 and 10
@settings(max_examples=300, deadline=None)
@given(raw=st.one_of(_raw_lists, _unique_cores))
def test_subquestion_count_always_between_3_and_10(raw: list) -> None:
    distinct = _distinct_count(raw)

    if distinct < MIN_SUBQUESTIONS:
        # Under-decomposition is a failure: no sub-questions are used.
        try:
            clamp_subquestions(raw)
        except LLMGatewayError as exc:
            assert exc.details.get("sub_question_count") == distinct
            return
        raise AssertionError(f"expected LLMGatewayError for distinct={distinct}")

    used = clamp_subquestions(raw)

    # The number of sub-questions USED is always in [3, 10] (Requirement 7.1).
    assert MIN_SUBQUESTIONS <= len(used) <= MAX_SUBQUESTIONS

    # Entries are distinct, trimmed, and preserve the LLM's first-seen order.
    assert len(used) == len(set(used))
    assert all(s == s.strip() and s for s in used)
    expected_prefix = _distinct_in_order(raw)[:MAX_SUBQUESTIONS]
    assert used == expected_prefix

    # Region-specific length checks.
    if distinct > MAX_SUBQUESTIONS:
        assert len(used) == MAX_SUBQUESTIONS  # truncated
    else:
        assert len(used) == distinct  # unchanged (3..10)
