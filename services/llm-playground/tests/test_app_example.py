"""Unit/example tests for the LLM Playground service (Task 7.8 + endpoints).

Covers:
- SSE token relay over ``POST /generate`` (Requirement 4.4) with a mocked
  LLMClient.stream.
- Write-on-completion: completing a run writes the expected playground row via a
  stubbed HistoryRepository (Requirement 12.5).
- Persistence-failure indication carried on the terminal ``done`` event when the
  repository raises, while the result is still streamed (Requirement 12.4).
- Gateway error mid-stream surfaces a terminal ``error`` frame (Requirement 4.5).
- ``GET /health``; validation 422 without calling the gateway (Requirement 4.7);
  history list/detail/404/502 (Requirements 13.1, 13.3, 13.6).
- Startup config validation names missing variables (Requirements 3.9, 3.13).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import ai_shared.config as config
from ai_shared.errors import LLMGatewayError, MissingConfigError, PersistenceError
from ai_shared.history import PlaygroundRecord, PlaygroundResult, ProjectId
from ai_shared.history import build_history_record
from ai_shared.llm_types import StreamEvent, Usage
from ai_shared.sse import parse_sse_frame

from app import main as main_module

from .conftest import FakeStreamClient, StubRepository


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_frames(text: str) -> list[tuple[str, dict]]:
    """Split a raw SSE body into parsed ``(event_type, data)`` frames."""
    frames: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if block.strip():
            frames.append(parse_sse_frame(block))
    return frames


@contextmanager
def _client(monkeypatch, *, stream_client, repository):
    """A TestClient whose app.state.client/repository are the supplied fakes.

    Sets dummy required env vars and disables real ``.env`` discovery so the
    lifespan's ``load_settings`` succeeds without depending on the machine's
    environment, then swaps in the fakes after startup.
    """
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in ("LLM_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("DB_PORT", "5432")

    with TestClient(main_module.app) as client:
        main_module.app.state.client = stream_client
        main_module.app.state.repository = repository
        yield client


def _ok_stream(usage: Usage | None = None) -> list[StreamEvent]:
    events = [
        StreamEvent(type="data", data={"text": "Hello"}),
        StreamEvent(type="data", data={"text": ", world"}),
    ]
    done_data = {"usage": usage.to_dict()} if usage is not None else {}
    events.append(StreamEvent(type="done", data=done_data))
    return events


# --------------------------------------------------------------------------- #
# 4.4 — SSE token relay
# --------------------------------------------------------------------------- #
def test_generate_relays_tokens_in_order(monkeypatch):
    usage = Usage(prompt_tokens=3, output_tokens=5, total_tokens=8)
    stream_client = FakeStreamClient(_ok_stream(usage))
    repo = StubRepository()

    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "Hi"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)
    data_texts = [d["text"] for (etype, d) in frames if etype == "data"]
    assert data_texts == ["Hello", ", world"]  # relayed in order (4.4)

    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    assert done[0]["usage"] == {"prompt_tokens": 3, "output_tokens": 5, "total_tokens": 8}


# --------------------------------------------------------------------------- #
# 12.5 — write-on-completion writes the expected playground row
# --------------------------------------------------------------------------- #
def test_completion_writes_expected_playground_row(monkeypatch):
    usage = Usage(prompt_tokens=7, output_tokens=11, total_tokens=18)
    stream_client = FakeStreamClient(_ok_stream(usage))
    repo = StubRepository()

    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post(
            "/generate",
            json={
                "prompt": "Explain SSE",
                "system_prompt": "Be concise",
                "temperature": 0.5,
                "max_tokens": 256,
            },
        )
    assert resp.status_code == 200

    # Exactly one record persisted, to the PLAYGROUND table, with all fields.
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.PLAYGROUND
    assert isinstance(record, PlaygroundRecord)
    assert record.prompt == "Explain SSE"
    assert record.system_prompt == "Be concise"
    assert record.temperature == 0.5
    assert record.max_tokens == 256
    assert record.model == "claude-opus-4.7"  # default model resolved
    assert record.response_text == "Hello, world"
    assert record.usage == {"prompt_tokens": 7, "output_tokens": 11, "total_tokens": 18}
    assert record.created_at is not None


def test_done_carries_persistence_ok_true_on_success(monkeypatch):
    stream_client = FakeStreamClient(_ok_stream(Usage(1, 2, 3)))
    repo = StubRepository()
    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "Hi"})
    done = [d for (etype, d) in _parse_frames(resp.text) if etype == "done"][0]
    assert done["persistence"] == {"ok": True}


# --------------------------------------------------------------------------- #
# 12.4 — persistence-failure indication on done; result still streamed
# --------------------------------------------------------------------------- #
def test_persistence_failure_indication_on_done(monkeypatch):
    stream_client = FakeStreamClient(_ok_stream(Usage(1, 2, 3)))
    repo = StubRepository(should_fail=True)  # save_record raises PersistenceError

    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "Hi"})

    assert resp.status_code == 200
    frames = _parse_frames(resp.text)

    # The result was still streamed (data + a terminal done, NOT converted to error).
    assert [d["text"] for (etype, d) in frames if etype == "data"] == ["Hello", ", world"]
    assert all(etype != "error" for (etype, _) in frames)

    done = [d for (etype, d) in frames if etype == "done"]
    assert len(done) == 1
    persistence = done[0]["persistence"]
    assert persistence["ok"] is False
    assert isinstance(persistence["operation_id"], str) and persistence["operation_id"]
    # Token usage still rides alongside the persistence indication.
    assert done[0]["usage"] == {"prompt_tokens": 1, "output_tokens": 2, "total_tokens": 3}


# --------------------------------------------------------------------------- #
# 4.5 — gateway error mid-stream surfaces a terminal error frame
# --------------------------------------------------------------------------- #
def test_gateway_error_midstream_emits_error_frame(monkeypatch):
    # Two real chunks, then the gateway fails (no terminal done from the client).
    events = [
        StreamEvent(type="data", data={"text": "partial"}),
    ]
    stream_client = FakeStreamClient(
        events, raise_exc=LLMGatewayError(reason="gateway boom")
    )
    repo = StubRepository()

    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "Hi"})

    frames = _parse_frames(resp.text)
    # Partial content relayed, then a terminal error including the gateway reason.
    assert [d["text"] for (etype, d) in frames if etype == "data"] == ["partial"]
    errors = [d for (etype, d) in frames if etype == "error"]
    assert len(errors) == 1
    assert errors[0]["action"] == "generate"
    assert "gateway boom" in errors[0]["reason"]
    # No done event, and nothing persisted for a failed run.
    assert all(etype != "done" for (etype, _) in frames)
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health(monkeypatch):
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=StubRepository()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# 4.7 — validation error -> 422 and the gateway is never called
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": ""},  # empty prompt
        {"prompt": "x" * 8001},  # prompt too long
        {"prompt": "ok", "system_prompt": "s" * 4001},  # system prompt too long
        {"prompt": "ok", "temperature": 2.001},  # temperature out of range
        {"prompt": "ok", "max_tokens": 0},  # max_tokens out of range
        {"prompt": "ok", "max_tokens": 4097},  # max_tokens out of range
    ],
)
def test_invalid_request_returns_422_without_calling_gateway(monkeypatch, payload):
    stream_client = FakeStreamClient(_ok_stream())
    repo = StubRepository()
    with _client(monkeypatch, stream_client=stream_client, repository=repo) as client:
        resp = client.post("/generate", json=payload)

    assert resp.status_code == 422
    body = resp.json()
    assert "field" in body["error"]["details"]
    # The gateway was never contacted and nothing was persisted (4.7).
    assert stream_client.calls == []
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# 13.x — history endpoints
# --------------------------------------------------------------------------- #
class _ReadRepo:
    """A repository stub backing the read endpoints with in-memory rows."""

    def __init__(self, *, summaries=None, record=None, raise_on=None) -> None:
        from ai_shared.history import HistorySummary  # local import

        self._summaries = summaries or []
        self._record = record
        self._raise_on = raise_on or set()
        self._HistorySummary = HistorySummary

    def list_records(self, project):
        if "list" in self._raise_on:
            raise PersistenceError(reason="db down")
        return self._summaries

    def get_record(self, project, record_id):
        if "get" in self._raise_on:
            raise PersistenceError(reason="db down")
        return self._record


def _make_record() -> PlaygroundRecord:
    result = PlaygroundResult(
        prompt="p",
        system_prompt=None,
        temperature=1.0,
        max_tokens=64,
        model="claude-opus-4.7",
        response_text="answer",
        usage=Usage(1, 2, 3),
    )
    return build_history_record(ProjectId.PLAYGROUND, result)


def test_history_list_newest_first(monkeypatch):
    from datetime import datetime, timezone

    from ai_shared.history import HistorySummary

    summaries = [
        HistorySummary(id=2, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc), label="newer"),
        HistorySummary(id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), label="older"),
    ]
    repo = _ReadRepo(summaries=summaries)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == ["2", "1"]
    assert all("created_at" in item for item in body)


def test_history_detail_found(monkeypatch):
    repo = _ReadRepo(record=_make_record())
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "5"
    assert body["inputs"]["prompt"] == "p"
    assert body["outputs"]["response_text"] == "answer"
    assert body["outputs"]["usage"] == {"prompt_tokens": 1, "output_tokens": 2, "total_tokens": 3}


def test_history_detail_unknown_id_404(monkeypatch):
    repo = _ReadRepo(record=None)
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/999")
    assert resp.status_code == 404


def test_history_list_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on={"list"})
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_history_detail_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on={"get"})
    with _client(monkeypatch, stream_client=FakeStreamClient([]), repository=repo) as client:
        resp = client.get("/history/5")
    assert resp.status_code == 502


# --------------------------------------------------------------------------- #
# 3.9 / 3.13 — startup config validation names missing variables
# --------------------------------------------------------------------------- #
def test_startup_config_validation_names_missing_vars(monkeypatch):
    """load_settings(required=...) raises MissingConfigError naming missing DB_*/key.

    Exercises the exact required set the service uses at startup. With a clean
    environment (no .env, no env vars) every required variable is reported.
    """
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(MissingConfigError) as exc_info:
        config.load_settings(required=main_module.REQUIRED_ENV)

    missing = set(exc_info.value.names)
    assert missing == set(main_module.REQUIRED_ENV)


def test_startup_succeeds_when_required_present(monkeypatch):
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in ("LLM_API_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("DB_PORT", "5432")

    settings = config.load_settings(required=main_module.REQUIRED_ENV)
    assert settings.db_port == 5432
    assert settings.llm_model == "claude-opus-4.7"  # default applied
