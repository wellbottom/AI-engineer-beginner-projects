"""Unit/example tests for the Web Agent service (Task 9.10 + endpoints).

Covers:
- Answer streaming relay over ``POST /ask`` (Requirement 6.4) with a mocked
  TavilySearch + mocked LLMClient: token chunks relayed in order, then a terminal
  ``done`` carrying ≥1 citation (each URL drawn from the retrieved results).
- Write-on-completion: a produced answer writes the expected web-agent row via a
  stubbed HistoryRepository (Requirement 12.7) and the ``done`` carries the
  persistence indication (Requirement 12.4); a persistence failure still streams
  the answer and flags ``ok: false`` on ``done`` (not an error).
- Validation 422 without querying the Search_Provider or the gateway
  (Requirement 6.7).
- Zero-results endpoint behavior (Requirement 6.5).
- Search-failure endpoint behavior (Requirement 6.6).
- ``GET /health``; history list/detail/404/502 (Requirements 13.1, 13.3, 13.6).
- Startup config validation names missing variables incl. TAVILY_API_KEY + DB_*
  (Requirements 3.9, 3.13).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import ai_shared.config as config
from ai_shared.errors import LLMGatewayError, MissingConfigError, PersistenceError, SearchError
from ai_shared.history import ProjectId, WebAgentRecord
from ai_shared.llm_types import StreamEvent
from ai_shared.sse import parse_sse_frame

from app import main as main_module

from .conftest import FakeSearch, FakeStreamClient, StubRepository, make_results


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_frames(text: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if block.strip():
            frames.append(parse_sse_frame(block))
    return frames


@contextmanager
def _client(monkeypatch, *, search, stream_client, repository):
    """A TestClient whose app.state fakes are swapped in after startup."""
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in ("LLM_API_KEY", "TAVILY_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("DB_PORT", "5432")

    with TestClient(main_module.app) as client:
        main_module.app.state.search = search
        main_module.app.state.client = stream_client
        main_module.app.state.repository = repository
        yield client


def _ok_stream(parts: list[str]) -> list[StreamEvent]:
    events = [StreamEvent(type="data", data={"text": p}) for p in parts]
    events.append(StreamEvent(type="done", data={}))
    return events


# --------------------------------------------------------------------------- #
# 6.4 — answer streaming relay (mocked TavilySearch + mocked LLMClient)
# --------------------------------------------------------------------------- #
def test_ask_relays_answer_chunks_then_done_with_citations(monkeypatch):
    results = make_results(3)
    search = FakeSearch(results=results)
    stream_client = FakeStreamClient(_ok_stream(["The ", "answer ", "is 42."]))
    repo = StubRepository()

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "what is the answer?"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)

    # Answer chunks relayed in order (Requirement 6.4).
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    assert data_texts == ["The ", "answer ", "is 42."]

    # Exactly one terminal done carrying ≥1 citation, each URL from the retrieved set.
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    citations = done[0]["citations"]
    assert len(citations) >= 1
    retrieved_urls = {r.url for r in results}
    assert all(c["url"] in retrieved_urls for c in citations)

    # The search was queried with the ≤10 cap and 30s timeout.
    assert len(search.calls) == 1
    assert search.calls[0]["max_results"] == 10
    assert search.calls[0]["timeout"] == 30.0
    # The LLM received the question + sources for synthesis.
    assert len(stream_client.calls) == 1
    sent = stream_client.calls[0]["messages"]
    assert sent[0].role == "system"
    assert "what is the answer?" in sent[-1].content


# --------------------------------------------------------------------------- #
# 12.7 / 12.4 — write-on-completion + persistence indication on done
# --------------------------------------------------------------------------- #
def test_completion_writes_expected_web_agent_row_and_done_ok_true(monkeypatch):
    results = make_results(2)
    search = FakeSearch(results=results)
    stream_client = FakeStreamClient(_ok_stream(["Cited ", "answer."]))
    repo = StubRepository()

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "tell me about pgvector"})
    assert resp.status_code == 200

    # The expected web-agent row was written via the stubbed repository.
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.WEB_AGENT
    assert isinstance(record, WebAgentRecord)
    assert record.question == "tell me about pgvector"
    assert record.answer == "Cited answer."
    assert len(record.citations) >= 1
    retrieved_urls = {r.url for r in results}
    assert all(c["url"] in retrieved_urls for c in record.citations)
    assert record.created_at is not None

    done = [d for (etype, d) in _parse_frames(resp.text) if etype == "done"][0]
    assert done["persistence"] == {"ok": True}


def test_persistence_failure_indication_on_done(monkeypatch):
    search = FakeSearch(results=make_results(2))
    stream_client = FakeStreamClient(_ok_stream(["Hi"]))
    repo = StubRepository(should_fail=True)  # save_record raises PersistenceError

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "anything"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    # The answer was still streamed (not converted to an error).
    assert [d["text"] for (etype, d) in frames if etype == "data"] == ["Hi"]
    assert all(etype != "error" for (etype, _) in frames)
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    persistence = done[0]["persistence"]
    assert persistence["ok"] is False
    assert isinstance(persistence["operation_id"], str) and persistence["operation_id"]


# --------------------------------------------------------------------------- #
# 6.5 — zero results -> no-sources answer, empty citations, no LLM call
# --------------------------------------------------------------------------- #
def test_zero_results_no_sources_answer(monkeypatch):
    from app.logic import NO_SOURCES_MESSAGE

    search = FakeSearch(results=[])
    stream_client = FakeStreamClient(_ok_stream(["should-not-run"]))
    repo = StubRepository()

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "obscure question"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    assert data_texts == [NO_SOURCES_MESSAGE]
    # No LLM synthesis call.
    assert stream_client.calls == []
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    assert done[0]["citations"] == []
    # The no-sources answer is still persisted (a produced answer).
    assert len(repo.saved) == 1
    _, record = repo.saved[0]
    assert isinstance(record, WebAgentRecord)
    assert record.answer == NO_SOURCES_MESSAGE
    assert record.citations == []


# --------------------------------------------------------------------------- #
# 6.6 — search failure -> terminal error, no answer/citations, nothing persisted
# --------------------------------------------------------------------------- #
def test_search_failure_returns_error_no_answer(monkeypatch):
    search = FakeSearch(raise_exc=SearchError(reason="provider down"))
    stream_client = FakeStreamClient(_ok_stream(["should-not-run"]))
    repo = StubRepository()

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "what is rag?"})

    assert resp.status_code == 200  # the stream opened; the error is a terminal frame
    frames = _parse_frames(resp.text)
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == "ask"
    assert errors[0]["stage"] == "search"
    assert errors[0]["reason"] == "provider down"
    # No answer, no done, no LLM call, nothing persisted.
    assert all(etype not in ("data", "done") for (etype, _) in frames)
    assert stream_client.calls == []
    assert repo.saved == []


def test_gateway_failure_mid_synthesis_returns_error(monkeypatch):
    """A gateway failure during synthesis -> terminal error; nothing persisted."""
    search = FakeSearch(results=make_results(2))
    stream_client = FakeStreamClient(
        [StreamEvent(type="data", data={"text": "partial"})],
        raise_exc=LLMGatewayError(reason="gateway refused"),
    )
    repo = StubRepository()

    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json={"question": "synthesize this"})

    frames = _parse_frames(resp.text)
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == "ask"
    assert errors[0]["stage"] == "synthesis"
    assert errors[0]["reason"] == "gateway refused"
    assert all(etype != "done" for (etype, _) in frames)
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# 6.7 — validation error -> 422 and neither search nor gateway is called
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},  # empty
        {"question": "   "},  # whitespace-only
        {"question": "x" * 2001},  # too long
        {"question": 123},  # not a string
        {},  # missing question
    ],
)
def test_invalid_request_returns_422_without_calling_providers(monkeypatch, payload):
    search = FakeSearch(results=make_results(3))
    stream_client = FakeStreamClient(_ok_stream(["x"]))
    repo = StubRepository()
    with _client(monkeypatch, search=search, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/ask", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["field"] == "question"
    assert search.calls == []
    assert stream_client.calls == []
    assert repo.saved == []


def test_boundary_question_lengths_accepted(monkeypatch):
    """A 1-char and a 2000-char (trimmed) question are accepted (boundaries)."""
    for q in ("a", "a" * 2000, "   " + "a" * 2000 + "   "):
        search = FakeSearch(results=make_results(1))
        stream_client = FakeStreamClient(_ok_stream(["ok"]))
        with _client(monkeypatch, search=search, stream_client=stream_client, repository=StubRepository()) as client:
            resp = client.post("/ask", json={"question": q})
        assert resp.status_code == 200
        assert len(search.calls) == 1


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health(monkeypatch):
    with _client(
        monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=StubRepository()
    ) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "web-agent"


# --------------------------------------------------------------------------- #
# 13.x — history endpoints
# --------------------------------------------------------------------------- #
class _ReadRepo:
    """Repository stub backing GET /history (list) + GET /history/{id} (detail)."""

    def __init__(self, *, summaries=None, record=None, raise_on_list=False, raise_on_get=False):
        self._summaries = summaries or []
        self._record = record
        self._raise_on_list = raise_on_list
        self._raise_on_get = raise_on_get

    def list_records(self, project):
        if self._raise_on_list:
            raise PersistenceError(reason="db down")
        return self._summaries

    def get_record(self, project, record_id):
        if self._raise_on_get:
            raise PersistenceError(reason="db down")
        return self._record


def test_history_list_newest_first(monkeypatch):
    from ai_shared.history import HistorySummary

    summaries = [
        HistorySummary(id=2, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc), label="q-b"),
        HistorySummary(id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), label="q-a"),
    ]
    repo = _ReadRepo(summaries=summaries)
    with _client(monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == ["2", "1"]
    assert all(item["project_id"] == "web-agent" for item in body)


def test_history_list_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_list=True)
    with _client(monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_history_detail_found(monkeypatch):
    record = WebAgentRecord(
        question="what is rag?",
        answer="Retrieval-augmented generation.",
        citations=[{"url": "https://example.com/1", "title": "RAG"}],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo = _ReadRepo(record=record)
    with _client(monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "7"
    assert body["inputs"]["question"] == "what is rag?"
    assert body["outputs"]["answer"] == "Retrieval-augmented generation."
    assert body["outputs"]["citations"][0]["url"] == "https://example.com/1"


def test_history_detail_unknown_id_404(monkeypatch):
    repo = _ReadRepo(record=None)
    with _client(monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/999")
    assert resp.status_code == 404


def test_history_detail_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_get=True)
    with _client(monkeypatch, search=FakeSearch(), stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/5")
    assert resp.status_code == 502


# --------------------------------------------------------------------------- #
# 3.9 / 3.13 — startup config validation names missing variables
# --------------------------------------------------------------------------- #
def test_startup_config_validation_names_missing_vars(monkeypatch):
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(MissingConfigError) as exc_info:
        config.load_settings(required=main_module.REQUIRED_ENV)

    # Every required variable (incl. TAVILY_API_KEY + DB_*) is named.
    assert set(exc_info.value.names) == set(main_module.REQUIRED_ENV)
    assert "TAVILY_API_KEY" in exc_info.value.names


def test_startup_succeeds_when_required_present(monkeypatch):
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in ("LLM_API_KEY", "TAVILY_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("DB_PORT", "5432")

    settings = config.load_settings(required=main_module.REQUIRED_ENV)
    assert settings.db_port == 5432
    assert settings.tavily_api_key == "v"
    assert settings.llm_model == "claude-opus-4.7"
