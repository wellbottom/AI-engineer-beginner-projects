"""Property-based test for Web Agent citation construction (Property 11).

# Feature: ai-engineer-practice-monorepo, Property 11: from a non-empty retrieved set, citations are non-empty and every URL belongs to the retrieved sources

**Validates: Requirements 6.3, 7.5**

For any answer produced from a **non-empty** set of retrieved sources,
:func:`app.logic.build_citations` returns a non-empty citation list in which every
citation URL is a member of the URLs of the retrieved sources used to produce the
answer. The ``answer_sources`` the model "references" are generated as an arbitrary
mix of (a) URLs actually present in the retrieved set and (b) foreign URLs that are
NOT retrieved — the foreign URLs must never appear as citations, and even when the
model references nothing valid the citations still fall back to the retrieved set
(non-empty), since the answer was synthesized from those sources.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.search import WebResult
from app.logic import build_citations


def _result(i: int) -> WebResult:
    return WebResult(
        title=f"Result {i}",
        url=f"https://example.com/{i}",
        content=f"content {i}",
        rank=i,
    )


# A non-empty retrieved set of 1..12 distinct ranked results.
_retrieved = st.integers(min_value=1, max_value=12).map(
    lambda k: [_result(i + 1) for i in range(k)]
)

# Foreign URLs that are guaranteed NOT to be in the retrieved set.
_foreign_urls = st.lists(
    st.integers(min_value=1000, max_value=2000).map(lambda i: f"https://foreign.test/{i}"),
    max_size=6,
)


# Feature: ai-engineer-practice-monorepo, Property 11: from a non-empty retrieved set, citations are non-empty and every URL belongs to the retrieved sources
@settings(max_examples=200, deadline=None)
@given(retrieved=_retrieved, foreign=_foreign_urls, data=st.data())
def test_citations_non_empty_subset_of_retrieved(
    retrieved: list[WebResult], foreign: list[str], data
) -> None:
    retrieved_urls = {r.url for r in retrieved}

    # The answer "references" an arbitrary mix of real retrieved URLs + foreign ones,
    # in an arbitrary order (and possibly nothing valid at all).
    real_subset = data.draw(st.lists(st.sampled_from([r.url for r in retrieved]), max_size=8))
    answer_sources = data.draw(st.permutations(real_subset + foreign))

    citations = build_citations(answer_sources, retrieved)

    # Non-empty (the retrieved set is non-empty -> the answer carries ≥1 citation).
    assert len(citations) >= 1

    cited_urls = [c.url for c in citations]

    # Every citation URL is a member of the retrieved sources' URLs.
    assert all(url in retrieved_urls for url in cited_urls)

    # No foreign (non-retrieved) URL is ever cited.
    assert all(url not in cited_urls for url in foreign)

    # Citations are de-duplicated.
    assert len(cited_urls) == len(set(cited_urls))

    # Each citation's title matches the retrieved source it references.
    title_by_url = {r.url: r.title for r in retrieved}
    assert all(c.title == title_by_url[c.url] for c in citations)
