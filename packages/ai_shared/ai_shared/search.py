"""Tavily web-search provider wrapper (Requirements 6.1, 6.6; deep-research 7.9).

:class:`TavilySearch` is a thin, framework-agnostic wrapper over the Tavily
Search API used by both the Web_Agent (``services/web-agent``) and Deep Research
(``services/deep-research``). It performs one job: run a query and return a list
of ranked :class:`WebResult` objects in a normalized shape.

Design constraints honored here:

- **Normalized, ranked results.** Each Tavily hit is mapped onto a
  :class:`WebResult` (``title``, ``url``, ``content``, ``rank``) where ``rank``
  reflects Tavily's returned order (1-based, best first).
- **Capping.** ``max_results`` (default 10) caps how many results are returned,
  preserving ranked order. The Web_Agent enforces the ≤10 contract of
  Requirement 6.1 at the service layer; here the wrapper simply never returns
  more than the configured maximum.
- **Timeout + structured failure.** A per-call timeout (default 30s,
  Requirement 6.6) is passed to the provider, and any failure or timeout is
  surfaced as :class:`~ai_shared.errors.SearchError` carrying the provider
  reason. An optional ``sub_question`` is threaded through onto the
  ``SearchError`` for the deep-research per-sub-question case (Requirement 7.9).
- **Dependency isolation / testability.** The ``tavily`` SDK is imported lazily
  (only when a real client is first built), and a client can be injected via the
  ``client=`` constructor argument. This keeps the normalization / capping /
  error-mapping logic unit-testable with a stub — no live ``tavily`` client and
  no real API key are required. The API key is read from
  :attr:`Settings.tavily_api_key`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .config import Settings
from .errors import SearchError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tavily import TavilyClient

__all__ = ["WebResult", "TavilySearch", "DEFAULT_SEARCH_TIMEOUT", "DEFAULT_MAX_RESULTS"]

#: Default per-call search timeout in seconds (Requirement 6.6: ≤30s).
DEFAULT_SEARCH_TIMEOUT: float = 30.0

#: Default cap on the number of ranked results (Requirement 6.1: up to 10).
DEFAULT_MAX_RESULTS: int = 10


@dataclass
class WebResult:
    """A single normalized, ranked web search result.

    ``rank`` is 1-based and reflects the provider's ranked order (1 = best).
    """

    title: str
    url: str
    content: str
    rank: int

    def to_json(self) -> dict[str, Any]:
        """Serialize to a small JSON-able dict (for SSE payloads / persistence)."""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "rank": self.rank,
        }


def _normalize_results(raw_results: Any, max_results: int) -> list[WebResult]:
    """Map a Tavily ``results`` list onto capped, ranked :class:`WebResult` objects.

    Tolerates the provider returning ``None``/missing fields and is defensive about
    the container type so both the real SDK response (a ``dict`` with a
    ``"results"`` list of dicts) and lightweight test doubles work.

    The first ``max_results`` hits are kept, preserving the provider's order, and
    assigned 1-based ranks. ``max_results <= 0`` yields an empty list.
    """
    if not raw_results:
        return []
    if max_results <= 0:
        return []

    normalized: list[WebResult] = []
    for index, item in enumerate(raw_results):
        if index >= max_results:
            break
        title = item.get("title") if isinstance(item, dict) else getattr(item, "title", None)
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        normalized.append(
            WebResult(
                title=title or "",
                url=url or "",
                content=content or "",
                rank=index + 1,
            )
        )
    return normalized


class TavilySearch:
    """Tavily web-search wrapper producing normalized, ranked results.

    Args:
        settings: Loaded :class:`Settings` providing ``tavily_api_key``.
        client: Optional pre-built client exposing a ``search(query, ...)`` method
            (anything Tavily-compatible). When omitted, a real ``tavily.TavilyClient``
            is created lazily on first use. Injecting a stub here keeps the
            normalization / capping / error-mapping logic testable without a live
            ``tavily`` client.
        max_results: Default cap on returned results (Requirement 6.1).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: "TavilyClient | Any | None" = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> None:
        self._settings = settings
        self._client = client
        self._max_results = max_results

    @property
    def client(self) -> "TavilyClient | Any":
        """The underlying Tavily client, built lazily from settings if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> "TavilyClient":
        """Construct a real ``tavily.TavilyClient`` from the configured API key."""
        from tavily import TavilyClient  # noqa: PLC0415 - intentional lazy import

        return TavilyClient(api_key=self._settings.tavily_api_key)

    def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        timeout: float = DEFAULT_SEARCH_TIMEOUT,
        sub_question: str | None = None,
    ) -> list[WebResult]:
        """Query Tavily and return capped, ranked, normalized results.

        Args:
            query: The search query. (Empty/whitespace validation is the caller's
                responsibility per Requirements 6.7 / 7.8; this wrapper queries the
                provider as given.)
            max_results: Per-call override of the configured cap. Defaults to the
                instance's ``max_results``. Capping preserves ranked order.
            timeout: Per-call timeout in seconds passed to the provider
                (Requirement 6.6).
            sub_question: Optional Deep Research sub-question text threaded onto a
                raised :class:`SearchError` to identify the affected sub-question
                (Requirement 7.9).

        Returns:
            A list of :class:`WebResult` of length at most the effective cap,
            ranked 1..n in provider order. May be empty when the provider returns
            no results.

        Raises:
            SearchError: The provider failed or timed out; carries the provider
                reason and, when supplied, ``sub_question``.
        """
        cap = self._max_results if max_results is None else max_results

        try:
            response = self.client.search(
                query=query,
                max_results=cap if cap > 0 else 0,
                timeout=timeout,
            )
        except SearchError:
            # Already structured (e.g. an injected stub raised it directly): re-raise.
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY provider/transport error
            raise SearchError(
                reason=str(exc) or None,
                sub_question=sub_question,
            ) from exc

        raw_results = response.get("results") if isinstance(response, dict) else getattr(
            response, "results", None
        )
        return _normalize_results(raw_results, cap)
