"""Core Web Agent search + synthesis + persistence logic (Requirements 6.1-6.6, 12.7).

Framework-agnostic pieces of ``POST /ask`` so they are unit/property-testable
without spinning up FastAPI, a live Tavily client, or a live gateway:

- :func:`cap_results` — the **pure** result-cap function (Property 10): given the
  ``K`` ranked results returned by the Search_Provider, keep exactly ``min(K, 10)``
  of them, preserving ranked order. Reuses :data:`ai_shared.search.DEFAULT_MAX_RESULTS`
  (10) as the single source of the cap so the service never duplicates the bound.
- :func:`build_citations` — the **pure** citation-construction function
  (Property 11): from the answer's source URLs and the retrieved results, produce
  citations whose URL is always a member of the retrieved sources' URLs, and which
  are non-empty whenever the retrieved set is non-empty (Requirements 6.3, 7.5).
- :func:`build_messages` — assemble the LLM request (a synthesis system prompt plus
  a user message carrying the question and the numbered retrieved sources).
- :func:`ask_sse` — an async generator that drives the turn: validate-then-search
  (the handler validates first, Requirement 6.7), cap to ≤10 ranked results
  (Requirement 6.1), and then:
    * **zero results** → stream the canned "no relevant web sources found" answer as
      ``data`` and a terminal ``done`` with an **empty** citation list; the LLM is
      **not** called for synthesis (Requirement 6.5). The no-sources answer *is* a
      produced answer, so it is persisted (decision below).
    * **≥1 result** → stream the synthesized answer from :meth:`LLMClient.stream`
      as ``data`` (Requirements 6.2, 6.4), then a terminal ``done`` carrying ≥1
      citation, each URL drawn from the retrieved results (Requirement 6.3).
    * **search failure / 30s timeout** → a terminal ``error`` identifying the
      search failure, with **no** synthesized answer and an **empty** citation list;
      **nothing** is persisted (Requirement 6.6, Property 13).
    * **gateway failure mid-synthesis** → a terminal ``error`` carrying the gateway
      reason; nothing is persisted (consistent with Property 2).

Persistence policy (Requirement 12.7, design "History-write-failure policy"):
- An answer that is *produced* — a synthesized answer **or** the no-sources answer —
  is persisted as a :class:`ai_shared.history.WebAgentResult` (question, answer,
  citations) and the persistence-failure indication rides on the terminal ``done``
  event (Requirement 12.4), never converting a successful stream into an ``error``.
- A *search failure* produces no answer, so nothing is persisted.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Iterable

from ai_shared.errors import LLMGatewayError, LLMTimeoutError, SearchError
from ai_shared.history import (
    Citation,
    HistoryRepository,
    ProjectId,
    WebAgentResult,
    build_history_record,
)
from ai_shared.llm_client import LLMClient
from ai_shared.llm_types import Message
from ai_shared.persistence import persist_record
from ai_shared.search import DEFAULT_MAX_RESULTS, WebResult
from ai_shared.sse import format_data, format_done, format_error

__all__ = [
    "cap_results",
    "build_citations",
    "build_messages",
    "ask_sse",
    "ACTION",
    "MAX_RESULTS",
    "SEARCH_TIMEOUT_SECONDS",
    "NO_SOURCES_MESSAGE",
    "SYNTHESIS_SYSTEM_PROMPT",
]

#: Human-readable action label used on terminal ``error`` frames (Requirements 6.6).
ACTION = "ask"

#: The configured maximum number of ranked results the Web_Agent uses
#: (Requirement 6.1: "up to a configured maximum of 10"). Reuses the shared
#: default so the cap is defined in exactly one place.
MAX_RESULTS = DEFAULT_MAX_RESULTS

#: This service's Search_Provider timeout (Requirement 6.6: fail/timeout within 30s).
SEARCH_TIMEOUT_SECONDS = 30.0

#: The terminal response when the Search_Provider returns zero results
#: (Requirement 6.5). Carries no citations.
NO_SOURCES_MESSAGE = (
    "No relevant web sources were found for your question, so I can't provide a "
    "cited answer. Please try rephrasing or asking a different question."
)

#: System prompt instructing the LLM to synthesize a cited answer from the
#: retrieved sources only (Requirement 6.2).
SYNTHESIS_SYSTEM_PROMPT = (
    "You are a web research assistant. Using ONLY the numbered web sources provided "
    "by the user, write a concise, accurate answer to their question. Base every "
    "claim on the supplied sources and do not invent facts that are not supported "
    "by them."
)


def cap_results(results: list[WebResult]) -> list[WebResult]:
    """Return the first ``min(K, 10)`` results, preserving ranked order (Property 10).

    Pure function. ``K`` is ``len(results)``; the cap is :data:`MAX_RESULTS` (10).
    A list slice keeps the provider's ranked order intact and never reorders or
    duplicates results. Fewer than the cap results are returned unchanged; an empty
    input yields an empty list.

    Args:
        results: The ranked results returned by the Search_Provider (rank 1 first).

    Returns:
        The first ``min(len(results), MAX_RESULTS)`` results, in order.
    """
    return list(results[:MAX_RESULTS])


def _source_url(source: Any) -> str | None:
    """Extract a URL string from a heterogeneous answer-source item.

    Accepts a plain URL string, a mapping with a ``"url"`` key, or any object with
    a ``url`` attribute (e.g. :class:`WebResult` / :class:`Citation`). Returns
    ``None`` when no usable URL is present.
    """
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        url = source.get("url")
        return url if isinstance(url, str) else None
    url = getattr(source, "url", None)
    return url if isinstance(url, str) else None


def build_citations(
    answer_sources: Iterable[Any],
    retrieved_results: list[WebResult],
) -> list[Citation]:
    """Build the answer's citations as a non-empty subset of retrieved URLs.

    Pure function (Property 11). The returned citations satisfy two invariants for
    any **non-empty** ``retrieved_results``:

    1. Every citation's URL is a member of the retrieved sources' URLs (a citation
       can only ever reference a URL that was actually retrieved — Requirements 6.3,
       7.5).
    2. The citation list is **non-empty** (an answer produced from retrieved sources
       always carries at least one citation — Requirement 6.3).

    Construction:
        * Index the retrieved results by URL (first occurrence wins for the title),
          preserving ranked order.
        * Keep each ``answer_sources`` URL that is present in the retrieved set,
          in answer order, de-duplicated.
        * If that intersection is empty but the retrieved set is non-empty, fall
          back to citing **all** retrieved sources in ranked order — the answer was
          synthesized from them, so they are the sources "used to produce" it.

    When ``retrieved_results`` is empty the result is an empty list (the zero-results
    path omits citations entirely, Requirement 6.5).

    Args:
        answer_sources: The source URLs the answer references (strings, mappings
            with a ``url`` key, or objects with a ``url`` attribute).
        retrieved_results: The retrieved :class:`WebResult` set used for the answer.

    Returns:
        The list of :class:`Citation` for the answer.
    """
    # Ordered, de-duplicated retrieved URLs + their (first-seen) titles.
    retrieved_titles: dict[str, str] = {}
    retrieved_order: list[str] = []
    for result in retrieved_results:
        url = result.url
        if not url:
            continue
        if url not in retrieved_titles:
            retrieved_titles[url] = result.title or ""
            retrieved_order.append(url)

    if not retrieved_order:
        return []

    # Keep answer-source URLs that were actually retrieved, in answer order.
    cited_urls: list[str] = []
    seen: set[str] = set()
    for source in answer_sources:
        url = _source_url(source)
        if url and url in retrieved_titles and url not in seen:
            seen.add(url)
            cited_urls.append(url)

    # Non-empty guarantee: fall back to all retrieved sources (ranked order).
    if not cited_urls:
        cited_urls = retrieved_order

    return [Citation(url=url, title=retrieved_titles[url]) for url in cited_urls]


def build_messages(question: str, results: list[WebResult]) -> list[Message]:
    """Assemble the LLM message list for answer synthesis (Requirement 6.2).

    The system prompt instructs source-grounded synthesis; the user message carries
    the question followed by the numbered retrieved sources (rank, title, URL, and
    content) so the model can cite them. Pure function — no I/O.
    """
    lines = [f"Question: {question}", "", "Web sources:"]
    for result in results:
        lines.append(f"[{result.rank}] {result.title} ({result.url})")
        if result.content:
            lines.append(result.content)
        lines.append("")
    user_content = "\n".join(lines).rstrip()
    return [
        Message(role="system", content=SYNTHESIS_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]


def _persist_answer(
    repository: HistoryRepository,
    question: str,
    answer: str,
    citations: list[Citation],
    operation_id_factory: Callable[[], str] | None,
):
    """Persist one produced answer best-effort; return the :class:`PersistenceOutcome`.

    Builds the ``WebAgentResult`` -> ``WebAgentRecord`` and writes it via the shared
    best-effort wrapper (Requirements 12.4, 12.7). Never raises for a persistence
    failure — the failure rides on the terminal ``done`` event.
    """
    result = WebAgentResult(question=question, answer=answer, citations=citations)
    record = build_history_record(ProjectId.WEB_AGENT, result)
    kwargs = {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    return persist_record(repository, ProjectId.WEB_AGENT, record, **kwargs)


async def ask_sse(
    question: str,
    *,
    search: Any,
    client: LLMClient,
    repository: HistoryRepository,
    operation_id_factory: Callable[[], str] | None = None,
) -> AsyncIterator[str]:
    """Stream one ask as SSE frames: search, synthesize, cite, and persist.

    The handler has already validated the question (Requirement 6.7), so this drives
    the search → synthesis → citation → persistence pipeline. See the module
    docstring for the four terminal cases (no-sources, synthesized answer, search
    failure, gateway failure).

    Args:
        question: The validated, trimmed question.
        search: A Search_Provider wrapper exposing
            ``search(query, *, max_results=None, timeout=...) -> list[WebResult]``
            (e.g. :class:`ai_shared.search.TavilySearch`). Raises
            :class:`ai_shared.errors.SearchError` on failure/timeout.
        client: The shared :class:`LLMClient`.
        repository: The shared :class:`HistoryRepository`.
        operation_id_factory: Optional deterministic id factory for tests.
    """
    # (1) Query the Search_Provider (≤30s). A failure/timeout is terminal: emit an
    # error identifying the search failure, with no answer and no citations, and
    # persist nothing (Requirement 6.6, Property 13).
    try:
        raw_results = search.search(
            question,
            max_results=MAX_RESULTS,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    except SearchError as exc:
        yield format_error(ACTION, exc.reason, stage="search")
        return

    # (2) Enforce the ≤10 ranked-result cap (Requirement 6.1, Property 10).
    results = cap_results(raw_results)

    # (3) Zero results: a no-sources answer with no citations; no LLM synthesis
    # (Requirement 6.5). It is a produced answer, so it is persisted.
    if not results:
        yield format_data(NO_SOURCES_MESSAGE)
        outcome = _persist_answer(
            repository, question, NO_SOURCES_MESSAGE, [], operation_id_factory
        )
        yield format_done(**outcome.attach_to_done({"citations": [], "no_sources": True}))
        return

    # (4) ≥1 result: synthesize the answer from the retrieved content and stream it.
    messages = build_messages(question, results)
    answer_parts: list[str] = []
    try:
        async for event in client.stream(messages, timeout=SEARCH_TIMEOUT_SECONDS):
            if event.type == "data":
                text = event.data.get("text", "")
                if text:
                    answer_parts.append(text)
                    yield format_data(text)
            elif event.type == "done":
                # The client's terminal event signals completion; the service emits
                # its own terminal `done` (with citations + persistence) below.
                break
    except (LLMTimeoutError, LLMGatewayError) as exc:
        # Gateway timeout/error (possibly mid-stream): terminal error with the
        # gateway reason. Nothing is persisted for a failed synthesis.
        yield format_error(ACTION, exc.reason, stage="synthesis")
        return

    # (5) Build citations drawn from the retrieved results (≥1; each URL a member of
    # the retrieved sources), persist the produced answer, and emit terminal `done`.
    answer = "".join(answer_parts)
    answer_sources = [r.url for r in results]
    citations = build_citations(answer_sources, results)
    outcome = _persist_answer(repository, question, answer, citations, operation_id_factory)
    done_payload = {"citations": [c.to_json() for c in citations]}
    yield format_done(**outcome.attach_to_done(done_payload))
