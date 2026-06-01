"""Property-based test for playground parameter pass-through (Property 4).

# Feature: ai-engineer-practice-monorepo, Property 4: the LLM request carries exactly the given valid temperature and max output tokens

**Validates: Requirements 4.3**

For any valid temperature and max-output-token value, the request the service
builds for the LLM_Client carries **exactly** that temperature and that max output
tokens. The test drives the *real* :class:`ai_shared.llm_client.LLMClient` (with a
fake openai-style SDK client that records the params handed to
``chat.completions.create``) through :func:`app.logic.generate_sse`, then asserts
the recorded request params equal the validated request's values verbatim.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.llm_client import LLMClient
from app.logic import generate_sse
from app.schemas import (
    MAX_TOKENS_MAX,
    MAX_TOKENS_MIN,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    PlaygroundRequest,
)

from .conftest import RecordingSDKClient, StubRepository


class _FakeSettings:
    """Minimal stand-in for Settings (only fields LLMClient reads)."""

    llm_base_url = "http://localhost:3090/v1"
    llm_api_key = "test-key"
    llm_model = "claude-opus-4.7"


_valid_temperature = st.floats(
    min_value=TEMPERATURE_MIN,
    max_value=TEMPERATURE_MAX,
    allow_nan=False,
    allow_infinity=False,
)
_valid_max_tokens = st.integers(min_value=MAX_TOKENS_MIN, max_value=MAX_TOKENS_MAX)


# Feature: ai-engineer-practice-monorepo, Property 4: the LLM request carries exactly the given valid temperature and max output tokens
@settings(max_examples=200, deadline=None)
@given(
    temperature=_valid_temperature,
    max_tokens=_valid_max_tokens,
    prompt=st.text(min_size=1, max_size=40),
)
def test_request_carries_exact_temperature_and_max_tokens(
    temperature: float, max_tokens: int, prompt: str
) -> None:
    sdk = RecordingSDKClient()
    client = LLMClient(_FakeSettings(), client=sdk)
    repo = StubRepository()
    request = PlaygroundRequest(
        prompt=prompt,
        system_prompt=None,
        temperature=temperature,
        max_tokens=max_tokens,
        model=None,
    )

    async def run() -> None:
        async for _ in generate_sse(
            request, client, repo, default_model=_FakeSettings.llm_model
        ):
            pass

    asyncio.run(run())

    # Exactly one gateway request was built, and it carries the params verbatim.
    assert len(sdk.params) == 1
    params = sdk.params[0]
    assert params["temperature"] == temperature
    assert params["max_tokens"] == max_tokens
