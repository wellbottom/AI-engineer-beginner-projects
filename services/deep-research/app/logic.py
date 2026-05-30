"""Core Deep Research pipeline: decompose → research → synthesize → persist.

This module holds the framework-agnostic pieces of ``POST /research`` so they are
unit/property-testable without spinning up FastAPI, a live Tavily/HF/Chroma client,
or a live gateway. It implements the design's pipeline (Requirements 7.1–7.6) plus
the per-failure behaviors (7.7, 7.9) and persistence (12.8).

Pure functions
--------------
- :func:`parse_decomposition` — turn the LLM's decomposition text into a list of
  candidate sub-question strings (strips numbering/bullets, drops blanks).
- :func:`clamp_subquestions` — the **pure** clamp (Property 15): normalize the raw
  list (trim, drop blanks, de-duplicate preserving order) and then keep the result
  in ``[3, 10]``. ``> 10`` distinct → **truncate** to the first 10; ``3..10`` →
  unchanged; ``< 3`` distinct → raise :class:`LLMGatewayError` (a decomposition
  failure — we never fabricate sub-questions). See BUG-008 for the rationale. This
  keeps the number of sub-questions *used* always in ``[3, 10]`` (Requirement 7.1).
- :func:`build_section_citations` — build a section's citations from the web
  results actually used for that sub-question (≥1 when the section drew on sources,
  Requirement 7.5).
- :func:`build_report_structure` — the **pure** report-assembly (Property 16): from
  a set of sub-questions produce a :class:`ResearchReport` with a title, an
  introduction, a conclusion, and **exactly one section per distinct sub-question**.

Pipeline
--------
- :func:`research_sse` — the async generator that drives the turn. The handler has
  already validated the topic (Requirement 7.8), so this:
    1. decomposes the topic via the LLM and clamps to ``[3, 10]`` (Requirement 7.1),
       emitting a ``progress`` (``decomposition``) step;
    2. **for each** sub-question: queries Tavily (Requirement 7.2) emitting a
       ``progress`` (``search``) step, then embeds + stores the retrieved content
       in Chroma via the Embeddings_Service (Requirement 7.3) emitting a
       ``progress`` (``embedding``) step;
    3. **only after all** sub-questions are researched, synthesizes the report from
       Vector_Store content via the LLM — title, introduction, one section per
       sub-question (each carrying ≥1 citation when it drew on sources), conclusion
       (Requirements 7.4, 7.5) — emitting a ``progress`` (``synthesis``) step;
    4. persists the completed report and emits a terminal ``done`` carrying the
       report + citations + the persistence indication (Requirements 12.8, 12.4).

  Terminal failures (each emits a terminal ``error`` frame and persists nothing):
    * **decomposition failure** (gateway error/timeout, or ``< 3`` sub-questions) →
      ``stage: "decomposition"``;
    * **per-sub-question search failure** → ``stage: "search"`` naming **both** the
      search failure **and** the affected sub-question (Requirement 7.9);
    * **embeddings/vector-store failure** (research storage or synthesis retrieval)
      → ``stage: "embedding"`` / ``"synthesis"`` identifying the embeddings failure
      (Requirement 7.7);
    * **synthesis gateway failure** → ``stage: "synthesis"``.

Persistence policy (Requirement 12.8, design "History-write-failure policy"):
- A **completed report** is persisted as a :class:`DeepResearchResult` (topic,
  sub-questions, full report, citations); the persistence-failure indication rides
  on the terminal ``done`` event (Requirement 12.4), never converting a successful
  stream into an ``error``.
- Any **mid-pipeline failure** (decomposition, search, embeddings) produces no
  completed report, so **nothing** is persisted.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, AsyncIterator, Callable, Iterable, Sequence

from ai_shared.errors import (
    EmbeddingsError,
    LLMGatewayError,
    LLMTimeoutError,
    SearchError,
)
from ai_shared.history import (
    Citation,
    DeepResearchResult,
    HistoryRepository,
    ProjectId,
    ReportSection,
    ResearchReport,
    SubQuestion,
    build_history_record,
)
from ai_shared.llm_client import LLMClient
from ai_shared.llm_types import Message
from ai_shared.persistence import persist_record
from ai_shared.search import DEFAULT_MAX_RESULTS, WebResult
from ai_shared.sse import format_done, format_error, format_progress
from ai_shared.vectorstore import VectorRecord

__all__ = [
    "parse_decomposition",
    "clamp_subquestions",
    "build_section_citations",
    "build_report_structure",
    "research_sse",
    "ACTION",
    "MIN_SUBQUESTIONS",
    "MAX_SUBQUESTIONS",
    "SEARCH_TIMEOUT_SECONDS",
    "EMBED_TIMEOUT_SECONDS",
    "DECOMPOSE_TIMEOUT_SECONDS",
    "SYNTHESIS_TIMEOUT_SECONDS",
    "RETRIEVAL_TOP_K",
    "PHASE_DECOMPOSITION",
    "PHASE_SEARCH",
    "PHASE_EMBEDDING",
    "PHASE_SYNTHESIS",
    "DECOMPOSE_SYSTEM_PROMPT",
    "SECTION_SYSTEM_PROMPT",
]

#: Human-readable action label used on terminal ``error`` frames.
ACTION = "research"

#: Inclusive sub-question bounds (Requirement 7.1: no fewer than 3, no more than 10).
MIN_SUBQUESTIONS = 3
MAX_SUBQUESTIONS = 10

#: Per-sub-question Search_Provider timeout (mirrors the shared 30s default).
SEARCH_TIMEOUT_SECONDS = 30.0
#: Embeddings/vector-store per-call timeout.
EMBED_TIMEOUT_SECONDS = 30.0
#: LLM timeouts for the decomposition and per-section synthesis calls.
DECOMPOSE_TIMEOUT_SECONDS = 60.0
SYNTHESIS_TIMEOUT_SECONDS = 60.0

#: How many stored chunks to retrieve from the Vector_Store per sub-question.
RETRIEVAL_TOP_K = 5

#: ``progress`` phase labels (Requirement 7.6).
PHASE_DECOMPOSITION = "decomposition"
PHASE_SEARCH = "search"
PHASE_EMBEDDING = "embedding"
PHASE_SYNTHESIS = "synthesis"

#: System prompt instructing the LLM to decompose a topic into sub-questions.
DECOMPOSE_SYSTEM_PROMPT = (
    "You are a research planner. Break the user's research topic into between "
    f"{MIN_SUBQUESTIONS} and {MAX_SUBQUESTIONS} focused, non-overlapping "
    "sub-questions that together cover the topic. Return one sub-question per "
    "line, with no numbering or commentary."
)

#: System prompt instructing the LLM to write one report section from sources.
SECTION_SYSTEM_PROMPT = (
    "You are a research writer. Using ONLY the provided sources, write a concise, "
    "accurate section answering the given sub-question. Base every claim on the "
    "supplied sources and do not invent facts that are not supported by them."
)

# Strips a leading list marker like "1.", "1)", "-", "*", "•" from a line.
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s*")


def parse_decomposition(text: str) -> list[str]:
    """Parse the LLM decomposition output into candidate sub-question strings.

    Pure function. Splits ``text`` on newlines, strips a leading list marker
    (``1.`` / ``1)`` / ``-`` / ``*`` / ``•``) and surrounding whitespace from each
    line, and drops blank lines. De-duplication and the ``[3, 10]`` clamp are
    applied separately by :func:`clamp_subquestions`.

    Args:
        text: The raw decomposition text returned by the LLM.

    Returns:
        The ordered candidate sub-question strings (may contain duplicates/blanks
        removed only at the line level).
    """
    candidates: list[str] = []
    for line in (text or "").splitlines():
        cleaned = _LIST_MARKER.sub("", line).strip()
        if cleaned:
            candidates.append(cleaned)
    return candidates


def _normalize_subquestions(raw_list: Iterable[Any]) -> list[str]:
    """Trim, drop blank/whitespace-only, and de-duplicate (first-seen) entries."""
    seen: set[str] = set()
    normalized: list[str] = []
    for item in raw_list:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized


def clamp_subquestions(raw_list: Iterable[Any]) -> list[str]:
    """Clamp a raw decomposition to between 3 and 10 distinct sub-questions.

    Pure function (Property 15). The returned list always has length in
    ``[MIN_SUBQUESTIONS, MAX_SUBQUESTIONS]`` and contains only distinct, non-blank,
    trimmed sub-questions, preserving the LLM's order. Clamp rule (BUG-008):

    * Normalize first — trim each entry, drop empty/whitespace-only entries, and
      de-duplicate preserving first-seen order.
    * ``> 10`` distinct → **truncate** to the first 10 (preserving order).
    * ``3..10`` distinct → returned unchanged.
    * ``< 3`` distinct → raise :class:`LLMGatewayError` (a decomposition failure).
      We deliberately do **not** pad/fabricate sub-questions, because invented
      sub-questions are not grounded in the LLM's decomposition; treating an
      under-decomposition as a failure keeps the report faithful and keeps the
      "number of sub-questions used is in [3, 10]" invariant true (no fabrication).

    Args:
        raw_list: The candidate sub-questions (e.g. from :func:`parse_decomposition`).

    Returns:
        A list of 3–10 distinct, trimmed sub-question strings.

    Raises:
        LLMGatewayError: When fewer than 3 distinct sub-questions remain after
            normalization (decomposition produced too few to research).
    """
    normalized = _normalize_subquestions(raw_list)

    if len(normalized) > MAX_SUBQUESTIONS:
        return normalized[:MAX_SUBQUESTIONS]

    if len(normalized) < MIN_SUBQUESTIONS:
        raise LLMGatewayError(
            action="topic decomposition",
            reason=(
                "Topic decomposition produced fewer than "
                f"{MIN_SUBQUESTIONS} distinct sub-questions "
                f"({len(normalized)}); cannot research the topic."
            ),
            details={"sub_question_count": len(normalized)},
        )

    return normalized


def build_section_citations(results: Sequence[WebResult]) -> list[Citation]:
    """Build a section's citations from the web results used for its sub-question.

    Pure function. De-duplicates by URL (first occurrence wins for the title),
    preserving ranked order, and skips results with no URL. A section that drew on
    one or more retrieved sources therefore carries **≥ 1** citation, each
    referencing a source URL actually used in that section (Requirement 7.5); a
    section with no sources yields an empty list (it draws on no sources).
    """
    titles: dict[str, str] = {}
    order: list[str] = []
    for result in results:
        url = result.url
        if not url:
            continue
        if url not in titles:
            titles[url] = result.title or ""
            order.append(url)
    return [Citation(url=url, title=titles[url]) for url in order]


def _default_title(topic: str) -> str:
    return f"Deep Research Report: {topic.strip()}" if topic.strip() else "Deep Research Report"


def _default_introduction(topic: str, subquestions: Sequence[str]) -> str:
    subject = topic.strip() or "the topic"
    return (
        f"This report synthesizes research on {subject}. It is organized around "
        f"{len(subquestions)} sub-questions, each researched from current web "
        "sources and answered in its own section below."
    )


def _default_conclusion(topic: str) -> str:
    subject = topic.strip() or "the topic"
    return (
        f"In summary, the sections above bring together the retrieved sources to "
        f"give a synthesized overview of {subject}."
    )


def build_report_structure(
    subquestions: Sequence[Any],
    *,
    topic: str = "",
    sections: Sequence[ReportSection] | None = None,
    title: str | None = None,
    introduction: str | None = None,
    conclusion: str | None = None,
) -> ResearchReport:
    """Assemble a :class:`ResearchReport` from a set of sub-questions (Property 16).

    Pure function. The produced report always has a (non-empty) title, a
    (non-empty) introduction, a (non-empty) conclusion, and **exactly one section
    per distinct sub-question**, in first-seen order — so the report structure
    matches the sub-question set (Requirement 7.4). Sub-questions are de-duplicated
    (trimmed, first-seen) so a duplicate never yields two sections.

    Args:
        subquestions: The sub-questions (``str`` or :class:`SubQuestion`); duplicates
            and blanks are collapsed/removed.
        topic: The research topic, used to build default title/intro/conclusion.
        sections: Optional pre-built sections (body + citations) produced by the
            synthesis step; matched to sub-questions by their ``sub_question`` text.
            A sub-question with no matching pre-built section gets an empty-body
            section (no sources drawn).
        title: Optional explicit title (defaults to one derived from ``topic``).
        introduction: Optional explicit introduction (defaults derived from topic).
        conclusion: Optional explicit conclusion (defaults derived from topic).

    Returns:
        A :class:`ResearchReport` whose ``sections`` align 1:1 with the distinct
        sub-questions.
    """
    texts: list[str] = []
    seen: set[str] = set()
    for sq in subquestions:
        text = sq.text if isinstance(sq, SubQuestion) else str(sq)
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)

    prebuilt: dict[str, ReportSection] = {}
    for section in sections or []:
        prebuilt.setdefault(section.sub_question.strip(), section)

    report_sections: list[ReportSection] = []
    for text in texts:
        existing = prebuilt.get(text)
        if existing is not None:
            report_sections.append(
                ReportSection(
                    sub_question=text,
                    body=existing.body,
                    citations=list(existing.citations),
                )
            )
        else:
            report_sections.append(ReportSection(sub_question=text, body="", citations=[]))

    return ResearchReport(
        title=title if title is not None and title.strip() else _default_title(topic),
        introduction=(
            introduction
            if introduction is not None and introduction.strip()
            else _default_introduction(topic, texts)
        ),
        sections=report_sections,
        conclusion=(
            conclusion
            if conclusion is not None and conclusion.strip()
            else _default_conclusion(topic)
        ),
    )


def _decompose_messages(topic: str) -> list[Message]:
    """Assemble the LLM message list for topic decomposition."""
    return [
        Message(role="system", content=DECOMPOSE_SYSTEM_PROMPT),
        Message(role="user", content=f"Research topic: {topic}"),
    ]


def _section_messages(
    topic: str,
    sub_question: str,
    sources: Sequence[WebResult],
    retrieved_texts: Sequence[str],
) -> list[Message]:
    """Assemble the LLM message list for one report section's synthesis.

    The user message carries the topic, the sub-question, and the numbered source
    content retrieved from the Vector_Store (and the web results) so the model can
    write a grounded section.
    """
    lines = [
        f"Research topic: {topic}",
        f"Sub-question: {sub_question}",
        "",
        "Sources:",
    ]
    seen: set[str] = set()
    index = 1
    for text in retrieved_texts:
        if text and text not in seen:
            seen.add(text)
            lines.append(f"[{index}] {text}")
            index += 1
    for result in sources:
        if result.content and result.content not in seen:
            seen.add(result.content)
            lines.append(f"[{index}] {result.title} ({result.url}) {result.content}")
            index += 1
    if index == 1:
        lines.append("(no sources were retrieved for this sub-question)")
    user_content = "\n".join(lines).rstrip()
    return [
        Message(role="system", content=SECTION_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]


async def _decompose(client: LLMClient, topic: str) -> list[str]:
    """Decompose ``topic`` into 3–10 distinct sub-questions via the LLM.

    Raises:
        LLMTimeoutError / LLMGatewayError: gateway failure or an under-decomposition
            (``< 3`` sub-questions, from :func:`clamp_subquestions`).
    """
    completion = await client.complete(
        _decompose_messages(topic), timeout=DECOMPOSE_TIMEOUT_SECONDS
    )
    candidates = parse_decomposition(completion.content)
    return clamp_subquestions(candidates)


async def _synthesize_section_body(
    client: LLMClient,
    topic: str,
    sub_question: str,
    sources: Sequence[WebResult],
    retrieved_texts: Sequence[str],
) -> str:
    """Synthesize one section's body text from its sources via the LLM."""
    completion = await client.complete(
        _section_messages(topic, sub_question, sources, retrieved_texts),
        timeout=SYNTHESIS_TIMEOUT_SECONDS,
    )
    return completion.content


def _dedupe_citations(citations: Iterable[Citation]) -> list[Citation]:
    """De-duplicate citations by URL across the whole report (first-seen order)."""
    seen: set[str] = set()
    out: list[Citation] = []
    for citation in citations:
        if citation.url and citation.url not in seen:
            seen.add(citation.url)
            out.append(citation)
    return out


def _persist_report(
    repository: HistoryRepository,
    topic: str,
    sub_questions: Sequence[SubQuestion],
    report: ResearchReport,
    citations: Sequence[Citation],
    operation_id_factory: Callable[[], str] | None,
):
    """Persist one completed report best-effort; return the :class:`PersistenceOutcome`.

    Builds the ``DeepResearchResult`` -> ``DeepResearchRecord`` and writes it via the
    shared best-effort wrapper (Requirements 12.4, 12.8). Never raises for a
    persistence failure — the failure rides on the terminal ``done`` event.
    """
    result = DeepResearchResult(
        topic=topic,
        sub_questions=list(sub_questions),
        report=report,
        citations=list(citations),
    )
    record = build_history_record(ProjectId.DEEP_RESEARCH, result)
    kwargs = {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    return persist_record(repository, ProjectId.DEEP_RESEARCH, record, **kwargs)


async def research_sse(
    topic: str,
    *,
    client: LLMClient,
    search: Any,
    embeddings: Any,
    vector_store: Any,
    repository: HistoryRepository,
    operation_id_factory: Callable[[], str] | None = None,
    collection_name: str | None = None,
) -> AsyncIterator[str]:
    """Stream one research run as SSE frames (Requirements 7.1–7.6, 12.8).

    The handler has already validated the topic (Requirement 7.8). See the module
    docstring for the full step sequence and the terminal failure cases.

    Args:
        topic: The validated, trimmed research topic.
        client: The shared :class:`LLMClient` (decomposition + section synthesis).
        search: A Search_Provider wrapper exposing
            ``search(query, *, max_results=None, timeout=..., sub_question=...) ->
            list[WebResult]`` (e.g. :class:`ai_shared.search.TavilySearch`).
        embeddings: An Embeddings_Service wrapper exposing
            ``embed(texts, *, timeout=...) -> list[list[float]]`` and
            ``embed_one(text, *, timeout=...) -> list[float]``
            (e.g. :class:`ai_shared.embeddings.HFEmbeddings`).
        vector_store: A Vector_Store wrapper exposing
            ``add(collection, records) -> int`` and
            ``query(collection, embedding, *, top_k=...) -> list[QueryHit]``
            (e.g. :class:`ai_shared.vectorstore.ChromaVectorStore`).
        repository: The shared :class:`HistoryRepository`.
        operation_id_factory: Optional deterministic id factory for tests.
        collection_name: Optional explicit Chroma collection (defaults to a unique
            per-run name) so concurrent runs do not mix content.
    """
    collection = collection_name or f"deep-research-{uuid.uuid4().hex}"
    step = 0

    # (1) Decompose the topic into 3–10 sub-questions (Requirement 7.1). A gateway
    # failure/timeout or an under-decomposition (< 3) is terminal: emit an error
    # identifying the decomposition failure and persist nothing.
    try:
        sub_question_texts = await _decompose(client, topic)
    except (LLMTimeoutError, LLMGatewayError) as exc:
        yield format_error(ACTION, exc.reason, stage=PHASE_DECOMPOSITION)
        return

    sub_questions = [
        SubQuestion(id=i + 1, text=text) for i, text in enumerate(sub_question_texts)
    ]
    step += 1
    yield format_progress(
        PHASE_DECOMPOSITION,
        step,
        detail=f"Decomposed the topic into {len(sub_questions)} sub-questions.",
        sub_question_count=len(sub_questions),
    )

    # (2) Research each sub-question: search (7.2) then embed + store (7.3),
    # emitting a progress step after each. No report part is built here (7.4).
    sub_question_results: dict[int, list[WebResult]] = {}
    for sq in sub_questions:
        # -- search --------------------------------------------------------- #
        try:
            results = search.search(
                sq.text,
                max_results=DEFAULT_MAX_RESULTS,
                timeout=SEARCH_TIMEOUT_SECONDS,
                sub_question=sq.text,
            )
        except SearchError as exc:
            # A per-sub-question search failure names BOTH the failure AND the
            # affected sub-question (Requirement 7.9). Nothing is persisted.
            yield format_error(
                ACTION,
                exc.reason,
                stage=PHASE_SEARCH,
                sub_question=sq.text,
                sub_question_id=sq.id,
            )
            return
        sub_question_results[sq.id] = list(results)
        step += 1
        yield format_progress(
            PHASE_SEARCH,
            step,
            detail=f"Searched the web for sub-question {sq.id}.",
            sub_question=sq.text,
            sub_question_id=sq.id,
            result_count=len(results),
        )

        # -- embed + store -------------------------------------------------- #
        try:
            records = _records_for(collection, sq, results, embeddings)
            vector_store.add(collection, records)
        except EmbeddingsError as exc:
            # Any embeddings/vector-store failure during research storage is
            # terminal and identifies the embeddings failure (Requirement 7.7).
            yield format_error(ACTION, exc.reason, stage=PHASE_EMBEDDING, sub_question_id=sq.id)
            return
        step += 1
        yield format_progress(
            PHASE_EMBEDDING,
            step,
            detail=f"Stored sources for sub-question {sq.id} in the vector store.",
            sub_question_id=sq.id,
            stored=len(records),
        )

    # (3) ONLY now that all sub-questions are researched, synthesize the report from
    # Vector_Store content via the LLM (Requirement 7.4). No report part was built
    # before this point.
    try:
        report, all_citations = await _synthesize_report(
            client, topic, sub_questions, sub_question_results, embeddings, vector_store, collection
        )
    except EmbeddingsError as exc:
        yield format_error(ACTION, exc.reason, stage=PHASE_SYNTHESIS)
        return
    except (LLMTimeoutError, LLMGatewayError) as exc:
        yield format_error(ACTION, exc.reason, stage=PHASE_SYNTHESIS)
        return

    step += 1
    yield format_progress(
        PHASE_SYNTHESIS,
        step,
        detail="Synthesized the report from the researched sub-questions.",
        sections=len(report.sections),
    )

    # (4) Persist the completed report (best-effort) and emit the terminal done with
    # the report + citations + persistence indication (Requirements 12.8, 12.4).
    outcome = _persist_report(
        repository, topic, sub_questions, report, all_citations, operation_id_factory
    )
    done_payload = {
        "report": report.to_json(),
        "citations": [c.to_json() for c in all_citations],
        "sub_questions": [sq.to_json() for sq in sub_questions],
    }
    yield format_done(**outcome.attach_to_done(done_payload))


def _records_for(
    collection: str,
    sq: SubQuestion,
    results: Sequence[WebResult],
    embeddings: Any,
) -> list[VectorRecord]:
    """Embed each result's content and build Chroma records for one sub-question.

    Raises:
        EmbeddingsError: The Embeddings_Service failed (Requirement 7.7).
    """
    contents = [r.content for r in results if r.content]
    sources = [r for r in results if r.content]
    if not contents:
        return []
    vectors = embeddings.embed(contents, timeout=EMBED_TIMEOUT_SECONDS)
    records: list[VectorRecord] = []
    for index, (result, vector) in enumerate(zip(sources, vectors)):
        records.append(
            VectorRecord(
                id=f"{collection}-{sq.id}-{index}",
                embedding=list(vector),
                document_text=result.content,
                metadata={
                    "source_url": result.url,
                    "title": result.title,
                    "sub_question_id": sq.id,
                },
            )
        )
    return records


async def _synthesize_report(
    client: LLMClient,
    topic: str,
    sub_questions: Sequence[SubQuestion],
    sub_question_results: dict[int, list[WebResult]],
    embeddings: Any,
    vector_store: Any,
    collection: str,
) -> tuple[ResearchReport, list[Citation]]:
    """Build the full report from Vector_Store content (Requirements 7.4, 7.5).

    For each sub-question: retrieve its stored content from the Vector_Store
    (embedding the sub-question text, then querying Chroma), synthesize the section
    body via the LLM, and attach citations drawn from the sub-question's sources.
    Returns the assembled report and its de-duplicated citation list.

    Raises:
        EmbeddingsError: An embeddings/vector-store retrieval failed.
        LLMTimeoutError / LLMGatewayError: The synthesis gateway call failed.
    """
    sections: list[ReportSection] = []
    all_citations: list[Citation] = []
    for sq in sub_questions:
        results = sub_question_results.get(sq.id, [])
        # Retrieve this sub-question's content from the Vector_Store (Requirement 7.4).
        query_vector = embeddings.embed_one(sq.text, timeout=EMBED_TIMEOUT_SECONDS)
        hits = vector_store.query(collection, query_vector, top_k=RETRIEVAL_TOP_K)
        retrieved_texts = [h.document_text for h in hits if getattr(h, "document_text", "")]

        body = await _synthesize_section_body(client, topic, sq.text, results, retrieved_texts)
        citations = build_section_citations(results)
        sections.append(ReportSection(sub_question=sq.text, body=body, citations=citations))
        all_citations.extend(citations)

    report = build_report_structure(
        [sq.text for sq in sub_questions],
        topic=topic,
        sections=sections,
    )
    return report, _dedupe_citations(all_citations)
