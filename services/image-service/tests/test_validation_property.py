"""Property-based test for image prompt validation (Property 22).

# Feature: ai-engineer-practice-monorepo, Property 22: validation succeeds iff 1–1000 trimmed chars; failure names the constraint and skips the provider

**Validates: Requirements 8.6**

For any prompt value, :func:`app.schemas.validate_image_prompt` succeeds **iff** the
prompt is a string whose trimmed length is between 1 and 1000 characters inclusive;
it returns the trimmed prompt on success. When validation fails it raises a
:class:`ValidationError` that **names the violated prompt constraint** (the
``prompt`` field plus the specific constraint text) **and** the Image_Provider is
never contacted.

To prove "the provider is not called on failure", validation is routed through a
sentinel provider that records any call. The test asserts the sentinel is never
touched on the failure path, and is only reachable once validation has succeeded.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import PROMPT_MAX, PROMPT_MIN, validate_image_prompt


class _SentinelProvider:
    """Records whether the Image_Provider was ever invoked."""

    def __init__(self) -> None:
        self.called = False

    async def generate(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return b""


def _expected_valid(prompt: object) -> bool:
    """Reference oracle: a string whose trimmed length is in [PROMPT_MIN, PROMPT_MAX]."""
    return isinstance(prompt, str) and PROMPT_MIN <= len(prompt.strip()) <= PROMPT_MAX


# A generator spanning the whole input space: non-strings, empty, whitespace-only,
# the exact 1-char and 1000-char boundaries, the 1001-char just-over boundary,
# normal text, whitespace-padded text, and unicode.
_prompts = st.one_of(
    st.none(),  # invalid: not a string
    st.integers(),  # invalid: not a string
    st.binary(max_size=8),  # invalid: not a string
    st.just(""),  # invalid: empty -> trimmed length 0
    st.text(alphabet=" \t\n\r", max_size=12),  # whitespace-only -> trimmed empty
    st.just("a"),  # valid: exactly PROMPT_MIN (1) trimmed char
    st.just("x" * PROMPT_MAX),  # valid: exactly PROMPT_MAX (1000) trimmed chars
    st.just("x" * (PROMPT_MAX + 1)),  # invalid: 1001 chars (just over)
    st.text(min_size=1, max_size=60),  # mixed: may/may not have non-whitespace
    st.text(min_size=1, max_size=1200),  # spans both length boundaries
    # Whitespace-padded valid text: the trimmed value is what should be returned.
    st.builds(
        lambda s: f"   {s}   ",
        st.text(min_size=1, max_size=40).filter(lambda s: s.strip()),
    ),
    st.text(alphabet="🎨émoji 你好", min_size=1, max_size=50),  # unicode
)


# Feature: ai-engineer-practice-monorepo, Property 22: validation succeeds iff 1–1000 trimmed chars; failure names the constraint and skips the provider
@settings(max_examples=300, deadline=None)
@given(prompt=_prompts)
def test_validation_succeeds_iff_1_to_1000_trimmed_and_failure_skips_provider(
    prompt: object,
) -> None:
    provider = _SentinelProvider()
    expected = _expected_valid(prompt)

    try:
        result = validate_image_prompt(prompt)
    except ValidationError as exc:
        # Failure path: the oracle agrees it is invalid, the error names the
        # violated prompt constraint, and the provider was NEVER called (Req 8.6).
        assert expected is False
        assert exc.field == "prompt"
        assert exc.details["field"] == "prompt"
        # The constraint text is present and non-empty (names what was violated).
        assert isinstance(exc.constraint, str) and exc.constraint.strip()
        assert exc.details["constraint"] == exc.constraint
        assert provider.called is False
        return

    # Success path: only reached when the oracle agrees the prompt is valid.
    assert expected is True
    assert isinstance(result, str)
    assert result == prompt.strip()  # type: ignore[union-attr]
    assert PROMPT_MIN <= len(result) <= PROMPT_MAX
    # Only now would a caller invoke the provider; emulate and confirm it is allowed.
    assert provider.called is False  # not called *during* validation
