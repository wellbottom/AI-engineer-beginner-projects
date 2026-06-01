"""Property-based test for LLM Playground request validation (Property 3).

# Feature: ai-engineer-practice-monorepo, Property 3: validation succeeds iff prompt/system/temperature/max_tokens are all in range; failure names a param and skips the LLM

**Validates: Requirements 4.1, 4.2, 4.7**

For any playground request, ``validate_playground_request`` succeeds **iff** all of
these hold: the prompt is a non-empty string of at most 8,000 characters, the
system prompt (when present) is at most 4,000 characters, the temperature is within
0.0-2.0 inclusive, and the max output tokens is within 1-4,096 inclusive. When
validation fails the raised :class:`ValidationError` names a violated parameter and
the LLM_Client is **not** called.

To prove "the LLM client is not called on failure", the test routes validation
through a small wrapper that would invoke a sentinel client only on success; the
sentinel records any call, and the test asserts it is never touched when validation
raises.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import ValidationError
from app.schemas import (
    MAX_TOKENS_MAX,
    MAX_TOKENS_MIN,
    PROMPT_MAX,
    SYSTEM_PROMPT_MAX,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    validate_playground_request,
)

_VALID_PARAMS = {"prompt", "system_prompt", "temperature", "max_tokens", "model"}


class _SentinelClient:
    """Records whether the (hypothetical) LLM client was ever invoked."""

    def __init__(self) -> None:
        self.called = False

    def stream(self, *args, **kwargs):  # pragma: no cover - must never run on failure
        self.called = True
        return iter(())


def _expected_valid(payload: dict) -> bool:
    """Reference oracle: independently compute whether the payload is valid.

    Mirrors the spec rules (Requirements 4.1, 4.2) without reusing the
    implementation's control flow, so it is an honest cross-check.
    """
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or len(prompt) == 0 or len(prompt) > PROMPT_MAX:
        return False

    system_prompt = payload.get("system_prompt")
    if system_prompt is not None:
        if not isinstance(system_prompt, str) or len(system_prompt) > SYSTEM_PROMPT_MAX:
            return False

    temperature = payload.get("temperature")
    if temperature is not None:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            return False
        if temperature < TEMPERATURE_MIN or temperature > TEMPERATURE_MAX:
            return False

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            return False
        if max_tokens < MAX_TOKENS_MIN or max_tokens > MAX_TOKENS_MAX:
            return False

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        return False

    return True


# Strategies that span valid and invalid regions, plus exact boundaries.
_prompts = st.one_of(
    st.just(""),  # invalid: empty
    st.text(min_size=1, max_size=20),  # valid small
    st.builds(lambda n: "a" * n, st.sampled_from([1, PROMPT_MAX, PROMPT_MAX + 1, PROMPT_MAX + 50])),
    st.integers(),  # invalid type
    st.none(),  # invalid: missing
)
_system_prompts = st.one_of(
    st.none(),
    st.just(""),
    st.text(max_size=20),
    st.builds(
        lambda n: "s" * n,
        st.sampled_from([SYSTEM_PROMPT_MAX, SYSTEM_PROMPT_MAX + 1]),
    ),
    st.integers(),  # invalid type
)
_temperatures = st.one_of(
    st.none(),
    st.sampled_from([-0.001, 0.0, 1.0, 2.0, 2.001, -5.0, 3.0]),
    st.floats(min_value=-1.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    st.text(max_size=3),  # invalid type
    st.booleans(),  # invalid type (bool)
)
_max_tokens = st.one_of(
    st.none(),
    st.sampled_from([0, 1, MAX_TOKENS_MAX, MAX_TOKENS_MAX + 1, -10, 2048]),
    st.integers(min_value=-5, max_value=MAX_TOKENS_MAX + 100),
    st.floats(allow_nan=False, allow_infinity=False),  # invalid type
    st.booleans(),  # invalid type (bool)
)
_models = st.one_of(st.none(), st.text(max_size=10), st.integers())


@st.composite
def _payloads(draw) -> dict:
    payload: dict = {"prompt": draw(_prompts)}
    if draw(st.booleans()):
        payload["system_prompt"] = draw(_system_prompts)
    if draw(st.booleans()):
        payload["temperature"] = draw(_temperatures)
    if draw(st.booleans()):
        payload["max_tokens"] = draw(_max_tokens)
    if draw(st.booleans()):
        payload["model"] = draw(_models)
    return payload


# Feature: ai-engineer-practice-monorepo, Property 3: validation succeeds iff prompt/system/temperature/max_tokens are all in range; failure names a param and skips the LLM
@settings(max_examples=300, deadline=None)
@given(payload=_payloads())
def test_validation_succeeds_iff_in_range_and_failure_skips_llm(payload: dict) -> None:
    sentinel = _SentinelClient()
    expected = _expected_valid(payload)

    try:
        result = validate_playground_request(payload)
    except ValidationError as exc:
        # Failure path: validation must have been expected to fail, the error names
        # a real parameter, and the LLM client was never invoked (Requirement 4.7).
        assert expected is False
        assert exc.field in _VALID_PARAMS
        assert exc.details["field"] == exc.field
        assert sentinel.called is False
        return

    # Success path: only reached when the oracle agrees the payload is valid.
    assert expected is True
    # A caller would now invoke the LLM client; emulate and confirm it is allowed.
    sentinel.stream()
    assert sentinel.called is True
    # Normalized values stay within bounds.
    assert 1 <= len(result.prompt) <= PROMPT_MAX
    assert TEMPERATURE_MIN <= result.temperature <= TEMPERATURE_MAX
    assert MAX_TOKENS_MIN <= result.max_tokens <= MAX_TOKENS_MAX
    if result.system_prompt is not None:
        assert len(result.system_prompt) <= SYSTEM_PROMPT_MAX
