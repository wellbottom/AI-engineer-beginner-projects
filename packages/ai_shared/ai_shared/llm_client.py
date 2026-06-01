"""Shared OpenAI-compatible LLM client (Requirements 3.3–3.8).

:class:`LLMClient` wraps the ``openai`` SDK pointed at the LLM_Gateway
(``base_url=settings.llm_base_url``, ``api_key=settings.llm_api_key``) and exposes
two coroutines used by every backend that talks to the gateway:

- :meth:`LLMClient.complete` — a non-streamed completion returning text + usage.
- :meth:`LLMClient.stream` — an async iterator of :class:`StreamEvent` that yields
  ``data`` chunks as they arrive and a terminal ``done`` event carrying token usage.

Design constraints honored here:

- **Model resolution** is the pure module function :func:`resolve_model`: a
  per-request, non-empty model id overrides the configured default; otherwise the
  default (``settings.llm_model``, in practice ``claude-opus-4.7``) is used
  (Requirements 3.4, 3.5).
- **Failure mapping** (Requirements 3.7, 3.8; Property 2): a timeout raises
  :class:`LLMTimeoutError`; any other gateway error or an unreachable connection
  raises :class:`LLMGatewayError`. The client **never fabricates content** — on a
  mid-stream failure it has yielded only the ``data`` chunks actually received
  from the gateway and then raises, so no completed/invented text and no terminal
  ``done`` is ever produced for a failed stream.
- **Dependency isolation / testability**: the ``openai`` SDK is imported lazily
  (only when a real client is first built), and the underlying async client can be
  injected via the ``client=`` constructor argument. This keeps :func:`resolve_model`
  and the stream-event handling unit/property-testable with a mock — no live
  ``openai`` network client is required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

from .config import Settings
from .errors import LLMGatewayError, LLMTimeoutError
from .llm_types import Completion, Message, StreamEvent, Usage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

__all__ = ["resolve_model", "LLMClient", "DEFAULT_TIMEOUT"]

#: Default per-request timeout in seconds (Requirement 3.7: abort after 60s).
DEFAULT_TIMEOUT: float = 60.0


def resolve_model(request_model: str | None, default: str) -> str:
    """Resolve the model id to use for a request (Requirements 3.4, 3.5).

    Returns ``request_model`` when it is a non-empty, non-whitespace string;
    otherwise returns ``default``. This is a pure function so it is directly
    property-testable without any ``openai`` import (Property 1).

    Args:
        request_model: A per-request model override, or ``None``.
        default: The configured fallback model (in practice ``claude-opus-4.7``).

    Returns:
        ``request_model`` if it carries a non-whitespace value, else ``default``.
    """
    if request_model is not None and request_model.strip():
        return request_model
    return default


# --- openai error-type plumbing (lazy, so importing this module needs no openai) --

_CACHED_ERROR_TYPES: tuple[type[BaseException] | None, tuple[type[BaseException], ...]] | None = None


def _openai_error_types() -> tuple[type[BaseException] | None, tuple[type[BaseException], ...]]:
    """Return ``(timeout_type, catchable_types)`` from the ``openai`` SDK.

    ``timeout_type`` is ``openai.APITimeoutError`` (or ``None`` if openai is not
    importable); ``catchable_types`` is the tuple of exception classes the client
    should treat as gateway/transport failures. Falls back to builtin
    transport errors when ``openai`` cannot be imported, so error mapping still
    works in a stripped-down environment.
    """
    global _CACHED_ERROR_TYPES
    if _CACHED_ERROR_TYPES is not None:
        return _CACHED_ERROR_TYPES

    builtin_transport: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, OSError)
    try:
        import openai  # noqa: PLC0415 - intentional lazy import

        timeout_type: type[BaseException] | None = openai.APITimeoutError
        catchable = (openai.OpenAIError, *builtin_transport)
    except Exception:  # pragma: no cover - openai is installed in this project
        timeout_type = None
        catchable = builtin_transport

    _CACHED_ERROR_TYPES = (timeout_type, catchable)
    return _CACHED_ERROR_TYPES


def _is_timeout(exc: BaseException) -> bool:
    """True if ``exc`` represents a timeout (openai ``APITimeoutError`` or builtin)."""
    timeout_type, _ = _openai_error_types()
    if timeout_type is not None and isinstance(exc, timeout_type):
        return True
    return isinstance(exc, TimeoutError)


def _map_and_raise(exc: BaseException, action: str) -> "Any":
    """Translate a gateway/transport exception into a structured ai_shared error.

    Timeouts → :class:`LLMTimeoutError`; everything else → :class:`LLMGatewayError`.
    The original exception is chained via ``from exc`` so the cause is preserved.
    """
    reason = str(exc) or None
    if _is_timeout(exc):
        raise LLMTimeoutError(action=action, reason=reason) from exc
    raise LLMGatewayError(action=action, reason=reason) from exc


# --- response-shape extraction helpers (pure, tolerant of mock/SDK objects) -------


def _extract_delta_text(chunk: Any) -> str | None:
    """Pull the incremental text from a streaming chat-completion chunk.

    Tolerates partial/empty chunks (e.g. the role-only first delta or a final
    usage-only chunk) by returning ``None`` when there is no content. Defensive
    ``getattr`` access means both real ``openai`` chunk objects and lightweight
    test doubles work.
    """
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return None
    content = getattr(delta, "content", None)
    return content if content else None


def _extract_usage(obj: Any) -> Usage | None:
    """Build a :class:`Usage` from an object carrying a ``usage`` attribute.

    Maps the gateway's ``completion_tokens`` onto :attr:`Usage.output_tokens`.
    Returns ``None`` when no usage is present (e.g. intermediate stream chunks).
    """
    usage = getattr(obj, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", None)
    output = getattr(usage, "completion_tokens", None)
    total = getattr(usage, "total_tokens", None)
    if prompt is None and output is None and total is None:
        return None
    prompt = int(prompt or 0)
    output = int(output or 0)
    total = int(total if total is not None else prompt + output)
    return Usage(prompt_tokens=prompt, output_tokens=output, total_tokens=total)


def _extract_message_text(completion: Any) -> str:
    """Pull the full assistant message text from a non-streamed completion."""
    choices = getattr(completion, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    return getattr(message, "content", "") or ""


class LLMClient:
    """OpenAI-compatible chat-completion client for the LLM_Gateway.

    Args:
        settings: Loaded :class:`Settings` providing ``llm_base_url``,
            ``llm_api_key``, and the default ``llm_model``.
        client: Optional pre-built async client (anything exposing
            ``chat.completions.create``). When omitted, a real ``openai.AsyncOpenAI``
            is created lazily on first use. Injecting a mock here keeps the
            failure/streaming logic testable without a live ``openai`` client.
    """

    def __init__(self, settings: Settings, *, client: "AsyncOpenAI | Any | None" = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def client(self) -> "AsyncOpenAI | Any":
        """The underlying async client, built lazily from settings if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> "AsyncOpenAI":
        """Construct a real ``openai.AsyncOpenAI`` pointed at the gateway."""
        from openai import AsyncOpenAI  # noqa: PLC0415 - intentional lazy import

        return AsyncOpenAI(
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
        )

    def _build_params(
        self,
        messages: list[Message],
        *,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        timeout: float,
    ) -> dict[str, Any]:
        """Assemble the kwargs for ``chat.completions.create``.

        Optional parameters are included only when provided so the gateway applies
        its own defaults otherwise. Model resolution uses :func:`resolve_model`.
        """
        params: dict[str, Any] = {
            "model": resolve_model(model, self._settings.llm_model),
            "messages": [m.to_dict() for m in messages],
            "timeout": timeout,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        return params

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Completion:
        """Run a non-streamed chat completion and return its text + usage.

        Raises:
            LLMTimeoutError: The gateway did not respond within ``timeout`` seconds.
            LLMGatewayError: The gateway returned an error or was unreachable.
        """
        params = self._build_params(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        _, catchable = _openai_error_types()
        try:
            completion = await self.client.chat.completions.create(**params)
        except catchable as exc:
            _map_and_raise(exc, action="LLM completion")

        return Completion(
            content=_extract_message_text(completion),
            usage=_extract_usage(completion),
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion as :class:`StreamEvent` objects.

        Yields one ``data`` event per non-empty content chunk as it arrives, then a
        single terminal ``done`` event carrying the token usage reported by the
        gateway (Requirement 4.6). On failure it raises after having yielded only
        the chunks actually received — never a ``done`` and never fabricated
        content (Requirements 3.7, 3.8; Property 2).

        Raises:
            LLMTimeoutError: The gateway timed out (before or during streaming).
            LLMGatewayError: The gateway errored or the connection failed.
        """
        params = self._build_params(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        params["stream"] = True
        # Ask the gateway to include a final usage chunk so the terminal `done`
        # event can carry prompt/output/total token counts.
        params["stream_options"] = {"include_usage": True}

        _, catchable = _openai_error_types()
        try:
            response = await self.client.chat.completions.create(**params)
        except catchable as exc:
            _map_and_raise(exc, action="LLM completion")

        usage: Usage | None = None
        try:
            async for chunk in response:
                text = _extract_delta_text(chunk)
                if text:
                    yield StreamEvent(type="data", data={"text": text})
                chunk_usage = _extract_usage(chunk)
                if chunk_usage is not None:
                    usage = chunk_usage
        except catchable as exc:
            # A failure after partial streaming: surface the error and stop. Only
            # the real chunks already yielded are present; no `done`, no fabrication.
            _map_and_raise(exc, action="LLM completion")

        yield StreamEvent(
            type="done",
            data={"usage": usage.to_dict()} if usage is not None else {},
        )
