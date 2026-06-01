"""Property-based test for per-project documentation section structure.

# Feature: ai-engineer-practice-monorepo, Property 29: each project's README/guide/key contain the required sections and the heading set is identical across projects per file type

**Validates: Requirements 10.2, 10.3, 10.4, 10.6**

The domain is small and closed (6 projects, 15 unordered pairs), so each example
is checked exhaustively for correctness; the Hypothesis ``@given`` sampling wraps
that exhaustive oracle to satisfy the project's >= 100-iteration property-test
convention. The tests are pure file-scanning (no DB, no providers).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from . import docs_utils as du


# --- Exhaustive checks (correctness) ---------------------------------------


def test_every_project_has_required_sections_per_file_type():
    """Requirements 10.2/10.3/10.4: each file type contains its required sections."""
    for slug in du.PROJECT_SLUGS:
        for filename, required in du.REQUIRED_SECTIONS.items():
            headings = du.section_headings(du.read_doc(slug, filename))
            missing = set(required) - headings
            assert not missing, (
                f"{slug}/{filename} is missing required section(s): "
                f"{sorted(missing)} (found {sorted(headings)})"
            )


def test_heading_set_identical_across_every_project_pair():
    """Requirement 10.6: per file type, every pair of projects shares one heading set."""
    for filename in du.DOC_FILES:
        for a, b in du.PROJECT_PAIRS:
            headings_a = du.section_headings(du.read_doc(a, filename))
            headings_b = du.section_headings(du.read_doc(b, filename))
            assert headings_a == headings_b, (
                f"{filename} heading sets differ between {a} and {b}: "
                f"{sorted(headings_a)} != {sorted(headings_b)}"
            )


# --- Hypothesis sampling (>= 100 iterations over the closed domain) ---------


@settings(max_examples=200, deadline=None)
@given(
    slug=st.sampled_from(du.PROJECT_SLUGS),
    filename=st.sampled_from(du.DOC_FILES),
)
def test_required_sections_present_for_any_sampled_project(slug, filename):
    """*For any* mini-project + file type, the required sections are present."""
    required = du.REQUIRED_SECTIONS[filename]
    headings = du.section_headings(du.read_doc(slug, filename))
    assert set(required) <= headings, (
        f"{slug}/{filename} missing {sorted(set(required) - headings)}"
    )


@settings(max_examples=200, deadline=None)
@given(
    pair=st.sampled_from(du.PROJECT_PAIRS),
    filename=st.sampled_from(du.DOC_FILES),
)
def test_heading_set_identical_for_any_sampled_pair(pair, filename):
    """*For any* two mini-projects, the heading set is identical per file type."""
    a, b = pair
    headings_a = du.section_headings(du.read_doc(a, filename))
    headings_b = du.section_headings(du.read_doc(b, filename))
    assert headings_a == headings_b, (
        f"{filename}: {a} {sorted(headings_a)} != {b} {sorted(headings_b)}"
    )
