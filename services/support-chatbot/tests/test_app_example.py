"""Unit/example tests for the Support Chatbot service (Task 8.11 + endpoints).

Covers:
- System-prompt loaded once at startup from configuration (Requirement 5.3).
- Out-of-scope canned reply with a STUBBED classifier; no LLM call, history kept
  (Requirement 5.4).
- SSE reply streaming over ``POST /chat`` (Requirement 5.5) with a mocked client.
- Write-on-completion: a completed turn writes the expected chatbot row via a
  stubbed HistoryRepository (Requirement 12.6) and the ``done`` carries the
  persistence indication (Requirement 12.4).
- Gateway refusal/timeout -> terminal ``error`` (temporarily unavailable),
  history preserved (Requirement 5.6).
- ``GET /health``; ``POST /session`` / ``DELETE /session/{id}`` (Requirement 5.1);
  validation 422 without calling the gateway (Requirement 5.7); history
  list/detail/404/502 (Requirements 13.1, 13.3, 13.6).
- Startup config validation names missing variables (Requirements 3.9, 3.13).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import ai_shared.config as config
from ai_shared.errors import LLMGatewayError, MissingConfigError, PersistenceError
from ai_shared.history import ChatTurnRecord, ProjectId
from ai_shared.llm_types import StreamEvent
from ai_shared.sse import parse_sse_frame

from app import main as main_module
from app.logic import OUT_OF_SCOPE_REPLY, TEMPORARILY_UNAVAILABLE
from app.session_store import SessionStore

from .conftest import FakeStreamClient, StubRepository


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
def _client(
    monkeypatch,
    *,
    stream_client,
    repository,
    classifier=None,
    system_prompt="You are a support assistant.",
    store=None,
):
    """A TestClient whose app.state fakes are swapped in after startup."""
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in ("LLM_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("DB_PORT", "5432")

    with TestClient(main_module.app) as client:
        main_module.app.state.client = stream_client
        main_module.app.state.repository = repository
        main_module.app.state.store = store if store is not None else SessionStore()
        main_module.app.state.system_prompt = system_prompt
        main_module.app.state.classifier = (
            classifier if classifier is not None else (lambda m, h: False)
        )
        yield client


def _ok_stream(parts: list[str]) -> list[StreamEvent]:
    events = [StreamEvent(type="data", data={"text": p}) for p in parts]
    events.append(StreamEvent(type="done", data={}))
    return events


# --------------------------------------------------------------------------- #
# 5.3 — system prompt loaded once at startup from configuration
# --------------------------------------------------------------------------- #
def test_system_prompt_loaded_from_literal_env(monkeypatch):
    from app.system_prompt import load_system_prompt

    prompt = load_system_prompt(env={"SUPPORT_SYSTEM_PROMPT": "  custom persona  "})
    assert prompt == "custom persona"


def test_system_prompt_loaded_from_file(monkeypatch, tmp_path):
    from app.system_prompt import load_system_prompt

    f = tmp_path / "prompt.txt"
    f.write_text("file persona and topics", encoding="utf-8")
    prompt = load_system_prompt(env={"SUPPORT_SYSTEM_PROMPT_FILE": str(f)})
    assert prompt == "file persona and topics"


def test_system_prompt_falls_back_to_bundled_default():
    from app.system_prompt import load_system_prompt

    # No env override + the real bundled file -> non-empty persona prompt.
    prompt = load_system_prompt(env={})
    assert isinstance(prompt, str) and prompt.strip()
    assert "support" in prompt.lower()


def test_system_prompt_loaded_once_and_used_in_stream(monkeypatch):
    """The startup-loaded prompt is the system message sent to the LLM (5.2/5.3)."""
    stream_client = FakeStreamClient(_ok_stream(["hi"]))
    with _client(
        monkeypatch,
        stream_client=stream_client,
        repository=StubRepository(),
        system_prompt="PERSONA-XYZ",
    ) as client:
        resp = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert resp.status_code == 200
    # The first message handed to the client is the startup-loaded system prompt.
    assert len(stream_client.calls) == 1
    sent = stream_client.calls[0]["messages"]
    assert sent[0].role == "system"
    assert sent[0].content == "PERSONA-XYZ"
    assert sent[-1].role == "user"
    assert sent[-1].content == "hello"
    # The service uses this service's 30s LLM timeout (Requirement 5.6).
    assert stream_client.calls[0]["timeout"] == 30.0


# --------------------------------------------------------------------------- #
# 5.4 — out-of-scope canned reply with a stubbed classifier
# --------------------------------------------------------------------------- #
def test_out_of_scope_returns_single_canned_reply_keeps_history_no_llm(monkeypatch):
    # Classifier stub: always out-of-scope.
    stream_client = FakeStreamClient(_ok_stream(["should-not-be-used"]))
    repo = StubRepository()
    store = SessionStore()

    with _client(
        monkeypatch,
        stream_client=stream_client,
        repository=repo,
        classifier=lambda m, h: True,
        store=store,
    ) as client:
        resp = client.post("/chat", json={"session_id": "s1", "message": "what's the weather?"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    # Exactly the single canned reply, no other assistant content.
    assert data_texts == [OUT_OF_SCOPE_REPLY]
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    assert done[0].get("out_of_scope") is True
    # The LLM client was never called (no other assistant reply generated).
    assert stream_client.calls == []
    # History is kept: the turn (with the canned reply) is retained + persisted.
    assert store.get("s1").turns[-1].assistant_reply == OUT_OF_SCOPE_REPLY
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.SUPPORT
    assert isinstance(record, ChatTurnRecord)
    assert record.assistant_reply == OUT_OF_SCOPE_REPLY


# --------------------------------------------------------------------------- #
# 5.5 — SSE reply streaming
# --------------------------------------------------------------------------- #
def test_chat_relays_reply_chunks_in_order(monkeypatch):
    stream_client = FakeStreamClient(_ok_stream(["Hel", "lo!", " How can I help?"]))
    with _client(monkeypatch, stream_client=stream_client, repository=StubRepository()) as client:
        resp = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    assert data_texts == ["Hel", "lo!", " How can I help?"]


# --------------------------------------------------------------------------- #
# 12.6 / 12.4 — write-on-completion + persistence indication on done
# --------------------------------------------------------------------------- #
def test_completion_writes_expected_chat_row_and_done_ok_true(monkeypatch):
    stream_client = FakeStreamClient(_ok_stream(["Hello", " there"]))
    repo = StubRepository()
    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/chat", json={"session_id": "sess-42", "message": "hi"})
    assert resp.status_code == 200

    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.SUPPORT
    assert isinstance(record, ChatTurnRecord)
    assert record.session_id == "sess-42"
    assert record.user_message == "hi"
    assert record.assistant_reply == "Hello there"
    assert record.created_at is not None

    done = [d for (etype, d) in _parse_frames(resp.text) if etype == "done"][0]
    assert done["persistence"] == {"ok": True}


def test_persistence_failure_indication_on_done(monkeypatch):
    stream_client = FakeStreamClient(_ok_stream(["Hi"]))
    repo = StubRepository(should_fail=True)  # save_record raises PersistenceError
    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/chat", json={"session_id": "s1", "message": "hi"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    # The reply was still streamed (not converted to an error).
    assert [d["text"] for (etype, d) in frames if etype == "data"] == ["Hi"]
    assert all(etype != "error" for (etype, _) in frames)
    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    persistence = done[0]["persistence"]
    assert persistence["ok"] is False
    assert isinstance(persistence["operation_id"], str) and persistence["operation_id"]


# --------------------------------------------------------------------------- #
# 5.6 — gateway refusal/timeout -> temporarily unavailable, history preserved
# --------------------------------------------------------------------------- #
def test_gateway_failure_returns_temporarily_unavailable_and_keeps_history(monkeypatch):
    stream_client = FakeStreamClient(
        [StreamEvent(type="data", data={"text": "partial"})],
        raise_exc=LLMGatewayError(reason="refused"),
    )
    repo = StubRepository()
    store = SessionStore()
    with _client(monkeypatch, stream_client=stream_client, repository=repo, store=store) as client:
        resp = client.post("/chat", json={"session_id": "s1", "message": "hi"})

    frames = _parse_frames(resp.text)
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == "chat"
    assert errors[0]["reason"] == TEMPORARILY_UNAVAILABLE
    assert all(etype != "done" for (etype, _) in frames)
    # History preserved: nothing appended/persisted for a failed turn.
    assert store.get("s1").turns == []
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# /health, /session
# --------------------------------------------------------------------------- #
def test_health(monkeypatch):
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_session_create_and_delete(monkeypatch):
    store = SessionStore()
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository(), store=store) as client:
        created = client.post("/session")
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        assert session_id

        deleted = client.delete(f"/session/{session_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        # Deleting an unknown session reports deleted=false.
        again = client.delete(f"/session/{session_id}")
        assert again.json()["deleted"] is False


# --------------------------------------------------------------------------- #
# 5.7 — validation error -> 422 and the gateway is never called
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s1", "message": ""},  # empty
        {"session_id": "s1", "message": "   "},  # whitespace-only
        {"session_id": "s1", "message": "x" * 4001},  # too long
        {"session_id": "s1", "message": 123},  # not a string
        {"session_id": "", "message": "hi"},  # missing session id
    ],
)
def test_invalid_request_returns_422_without_calling_gateway(monkeypatch, payload):
    stream_client = FakeStreamClient(_ok_stream(["x"]))
    repo = StubRepository()
    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 422
    assert "field" in resp.json()["error"]["details"]
    assert stream_client.calls == []
    assert repo.saved == []


def test_boundary_message_lengths_accepted(monkeypatch):
    """A 1-char and a 4000-char (trimmed) message are accepted (boundaries)."""
    for msg in ("a", "a" * 4000, "   " + "a" * 4000 + "   "):
        stream_client = FakeStreamClient(_ok_stream(["ok"]))
        with _client(monkeypatch, stream_client=stream_client, repository=StubRepository()) as client:
            resp = client.post("/chat", json={"session_id": "s1", "message": msg})
        assert resp.status_code == 200
        assert len(stream_client.calls) == 1


# --------------------------------------------------------------------------- #
# 13.x — history endpoints
# --------------------------------------------------------------------------- #
class _ReadRepo:
    """Repository stub backing GET /history (list) with in-memory summaries."""

    def __init__(self, *, summaries=None, raise_on_list=False) -> None:
        self._summaries = summaries or []
        self._raise_on_list = raise_on_list

    def list_records(self, project):
        if self._raise_on_list:
            raise PersistenceError(reason="db down")
        return self._summaries


def test_history_list_newest_first(monkeypatch):
    from ai_shared.history import HistorySummary

    summaries = [
        HistorySummary(id=2, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc), label="sess-b"),
        HistorySummary(id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), label="sess-a"),
    ]
    repo = _ReadRepo(summaries=summaries)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == ["2", "1"]
    assert all(item["project_id"] == "support" for item in body)


def test_history_list_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_list=True)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_history_detail_found(monkeypatch):
    """GET /history/{id} returns the session's full ordered turns via the reader."""
    from app.history_read import SessionDetail, SessionTurn

    detail = SessionDetail(
        session_pk=5,
        session_id="sess-5",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        turns=[
            SessionTurn("hi", "hello", datetime(2026, 1, 1, tzinfo=timezone.utc)),
            SessionTurn("bye", "goodbye", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ],
    )
    monkeypatch.setattr(main_module, "get_session_detail", lambda factory, pk: detail)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository()) as client:
        resp = client.get("/history/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "5"
    assert body["outputs"]["session_id"] == "sess-5"
    turns = body["outputs"]["turns"]
    assert [t["user_message"] for t in turns] == ["hi", "bye"]
    assert [t["assistant_reply"] for t in turns] == ["hello", "goodbye"]


def test_history_detail_unknown_id_404(monkeypatch):
    monkeypatch.setattr(main_module, "get_session_detail", lambda factory, pk: None)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository()) as client:
        resp = client.get("/history/999")
    assert resp.status_code == 404


def test_history_detail_retrieval_failure_502(monkeypatch):
    def _raise(factory, pk):
        raise PersistenceError(reason="db down")

    monkeypatch.setattr(main_module, "get_session_detail", _raise)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository()) as client:
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

    assert set(exc_info.value.names) == set(main_module.REQUIRED_ENV)


def test_startup_succeeds_when_required_present(monkeypatch):
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in ("LLM_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("DB_PORT", "5432")

    settings = config.load_settings(required=main_module.REQUIRED_ENV)
    assert settings.db_port == 5432
    assert settings.llm_model == "claude-opus-4.7"
