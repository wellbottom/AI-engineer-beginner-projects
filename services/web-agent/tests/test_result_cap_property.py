"""Property-based test for the Web Agent result cap (Property 10).

# Feature: ai-engineer-practice-monorepo, Property 10: exactly min(K,10) results used, preserving ranked order

**Validates: Requirements 6.1**

For any number ``K`` of ranked results returned by the Search_Provider,
:func:`app.logic.cap_results` uses exactly ``min(K, 10)`` of them and preserves
their ranked order (no reordering, no duplication, no gaps).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.search import WebResult
from app.logic import MAX_RESULTS, cap_results


def _result(rank: int) -> WebResult:
    """A WebResult whose fields encode its rank so order is checkable."""
    return WebResult(
        title=f"Result {rank}",
        url=f"https://example.com/{rank}",
        content=f"content {rank}",
        rank=rank,
    )


# K spans 0, the boundaries around the cap (9/10/11), and well above it. The
# range is kept wide enough (0..300) that the input space is not exhausted before
# the 200-iteration budget, so the property runs the full ≥100 iterations; the
# exact cap boundaries (0, 9, 10, 11) are always included.
_counts = st.one_of(
    st.sampled_from([0, 1, 9, 10, 11, 12]),
    st.integers(min_value=0, max_value=300),
)
_result_lists = _counts.map(lambda k: [_result(i + 1) for i in range(k)])


# Feature: ai-engineer-practice-monorepo, Property 10: exactly min(K,10) results used, preserving ranked order
@settings(max_examples=200, deadline=None)
@given(results=_result_lists)
def test_cap_keeps_exactly_min_k_10_preserving_order(results: list[WebResult]) -> None:
    k = len(results)
    capped = cap_results(results)

    # Exactly min(K, 10) results are used.
    assert len(capped) == min(k, MAX_RESULTS)
    assert MAX_RESULTS == 10

    # Ranked order is preserved: the capped list is the leading prefix of the input
    # (same objects, same order — no reordering, no duplication).
    assert capped == results[: min(k, MAX_RESULTS)]
    assert [r.rank for r in capped] == [r.rank for r in results[: min(k, MAX_RESULTS)]]

    # The result is a fresh list (the input is not mutated/aliased into the output).
    assert capped is not results
