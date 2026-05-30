"""Property-based test for key.md provider-list correctness.

# Feature: ai-engineer-practice-monorepo, Property 31: each key.md provider list equals that project's actual provider dependencies, or states none

**Validates: Requirements 10.5**

The expected provider set per project is encoded in ``docs_utils.EXPECTED_PROVIDERS``
(derived from the built services). The closed domain of 6 projects is checked
exhaustively; the Hypothesis ``@given`` sampling wraps that exhaustive oracle to
satisfy the >= 100-iteration property-test convention. Pure file-scanning (no DB,
no providers).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from . import docs_utils as du


def _external_providers_body(slug: str) -> str:
    markdown = du.read_doc(slug, "key.md")
    return du.section_body(markdown, "External Providers")


# --- Exhaustive check (correctness) ----------------------------------------


def test_key_md_provider_list_matches_actual_dependencies():
    """Requirement 10.5: listed providers equal the project's actual dependencies."""
    for slug in du.PROJECT_SLUGS:
        expected = du.EXPECTED_PROVIDERS[slug]
        body = _external_providers_body(slug)
        assert body.strip(), f"{slug}/key.md has no External Providers section body"

        listed = du.providers_listed(body)
        assert listed == set(expected), (
            f"{slug}/key.md lists {sorted(listed)} but actual dependencies are "
            f"{sorted(expected)}"
        )

        # No provider outside the closed five-name set can sneak in.
        assert listed <= du.ALL_PROVIDERS

        if not expected:
            # A no-dependency project must explicitly say so (none of the six here,
            # but the contract is asserted for completeness/future projects).
            assert du.states_depends_on_none(body), (
                f"{slug}/key.md depends on no providers but does not state 'none'"
            )


# --- Hypothesis sampling (>= 100 iterations over the closed domain) ---------


@settings(max_examples=200, deadline=None)
@given(slug=st.sampled_from(du.PROJECT_SLUGS))
def test_sampled_key_md_provider_list_matches(slug):
    """*For any* mini-project, its key.md provider list equals its dependencies."""
    expected = du.EXPECTED_PROVIDERS[slug]
    body = _external_providers_body(slug)
    listed = du.providers_listed(body)
    assert listed == set(expected), (
        f"{slug}/key.md lists {sorted(listed)} != actual {sorted(expected)}"
    )
    if not expected:
        assert du.states_depends_on_none(body)
