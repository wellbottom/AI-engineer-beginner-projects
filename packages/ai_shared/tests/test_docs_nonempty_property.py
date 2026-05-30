"""Property-based test for non-empty per-project documentation files.

# Feature: ai-engineer-practice-monorepo, Property 30: each project's README.md, guide.md, key.md exist and are non-empty

**Validates: Requirements 10.1**

The domain is the closed set of 6 projects x 3 files (18 docs), so each example is
checked exhaustively; the Hypothesis ``@given`` sampling wraps that exhaustive
oracle to satisfy the >= 100-iteration property-test convention. Pure file-scanning
(no DB, no providers).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from . import docs_utils as du


# --- Exhaustive check (correctness) ----------------------------------------


def test_every_project_doc_exists_and_is_non_empty():
    """Requirement 10.1: all three Project_Docs exist with non-empty content."""
    for slug in du.PROJECT_SLUGS:
        for filename in du.DOC_FILES:
            path = du.doc_path(slug, filename)
            assert path.is_file(), f"missing Project_Docs file: {path}"
            content = path.read_text(encoding="utf-8")
            assert content.strip(), f"Project_Docs file is empty: {path}"


# --- Hypothesis sampling (>= 100 iterations over the closed domain) ---------


@settings(max_examples=200, deadline=None)
@given(
    slug=st.sampled_from(du.PROJECT_SLUGS),
    filename=st.sampled_from(du.DOC_FILES),
)
def test_sampled_project_doc_is_non_empty(slug, filename):
    """*For any* of the six mini-projects, each doc file exists and is non-empty."""
    path = du.doc_path(slug, filename)
    assert path.is_file(), f"missing Project_Docs file: {path}"
    assert path.read_text(encoding="utf-8").strip(), f"empty Project_Docs file: {path}"
