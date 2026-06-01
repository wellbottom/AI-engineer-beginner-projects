"""Unit/example tests for the Capstone service (Task 12.13 + endpoints).

Covers, with MOCKED LLM/embeddings/vector-store/MCP (no network/token) and a
stubbed/injected repository via the FastAPI ``TestClient``:

- **9.2 MCP tool registration** — the MCP_Server exposes ≥1 tool; ``GET /tools``
  lists them; an unknown tool invocation is recorded as a failed tool.
- **9.4 agent capability wiring** — a task run can invoke MCP tools AND RAG retrieval.
- **9.9 task validation** — empty / whitespace task -> 422 and the Agent is not run.
- **9.10 ingestion embeddings failure** — surfaced as a 502 identifying the failure.
- **9.5 / 12.11 ingestion write-on-completion** — ``POST /documents`` confirms exactly
  the ingested documents and writes the ingest history row + ``persistence: ok``.
- **12.10 task write-on-completion** — a ``POST /task`` run writes the task history
  row (task text, final answer, tools with ok/failure, sources, step-limit) and the
  terminal ``done`` carries ``persistence: ok``.
- **12.4 persistence-failure indication** — a repository that raises still returns the
  result with ``persistence: {ok: false, operation_id}`` (done event + JSON body).
- **9.5 oversized document** — a >10 MB upload -> 422 naming the document.
- **13.1/13.3 history** — merged discriminated ids; detail by string id; 404; 502.
- **3.9/3.13 startup config validation** names the missing variables.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import ai_shared.config as config
from ai_shared.errors import MissingConfigError
from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneTaskRecord,
    HistorySummary,
    ProjectId,
)
from ai_shared.sse import parse_sse_frame

from app import main as main_module
from app.mcp import build_default_mcp_server

from .conftest import FakeCompleteClient, FakeEmbeddings, FakeVectorStore, StubRepository, make_query_hits


@contextmanager
def _client(monkeypatch, *, repository, embeddings=None, vector_store=None, client=None, mcp_server=None):
    """A TestClient whose app.state collaborators are the supplied fakes."""
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in ("LLM_API_KEY", "HF_TOKEN", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("DB_PORT", "5432")

    with TestClient(main_module.app) as test_client:
        main_module.app.state.repository = repository
        main_module.app.state.embeddings = embeddings or FakeEmbeddings()
        main_module.app.state.vector_store = vector_store or FakeVectorStore()
        main_module.app.state.mcp_server = mcp_server or build_default_mcp_server()
        # Default to a mocked LLM so answer synthesis never contacts a real gateway.
        main_module.app.state.client = client or FakeCompleteClient(["the synthesized answer"])
        yield test_client


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Split a raw SSE body into parsed (event_type, data) frames."""
    frames: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if block.strip():
            frames.append(parse_sse_frame(block + "\n\n"))
    return frames


class _ReadRepo:
    """Repository stub backing GET /history (list) and GET /history/{id} (detail)."""

    def __init__(self, *, summaries=None, record=None, raise_on_list=False, raise_on_get=False):
        self._summaries = summaries or []
        self._record = record
        self._raise_on_list = raise_on_list
        self._raise_on_get = raise_on_get
        self.requested_id = None

    def list_records(self, project):
        if self._raise_on_list:
            from ai_shared.errors import PersistenceError

            raise PersistenceError(reason="db down")
        return self._summaries

    def get_record(self, project, record_id):
        self.requested_id = record_id
        if self._raise_on_get:
            from ai_shared.errors import PersistenceError

            raise PersistenceError(reason="db down")
        return self._record


# --------------------------------------------------------------------------- #
# 9.2 — MCP tool registration exposes ≥1 tool
# --------------------------------------------------------------------------- #
def test_mcp_server_exposes_at_least_one_tool():
    server = build_default_mcp_server()
    specs = server.list_tools()
    assert len(specs) >= 1
    names = [s.name for s in specs]
    assert "word_count" in names  # a deterministic built-in tool
    # Each spec has a name + a non-empty description (MCP-shaped).
    for spec in specs:
        assert spec.name and spec.description


def test_tools_endpoint_lists_registered_tools(monkeypatch):
    with _client(monkeypatch, repository=StubRepository()) as client:
        resp = client.get("/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list) and tools
    names = [t["name"] for t in tools]
    assert "word_count" in names and "calculator" in names


def test_mcp_unknown_tool_is_recorded_as_failed():
    from app.agent import StepDecision, invoke_tool

    server = build_default_mcp_server()
    inv = invoke_tool(server, StepDecision(phase="tool_invocation", tool="nope", arguments={}))
    assert inv.tool == "nope"
    assert inv.ok is False
    assert inv.error


def test_health(monkeypatch):
    with _client(monkeypatch, repository=StubRepository()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# 9.9 — task validation -> 422, Agent not started
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("task", ["", "   ", "\t\n "])
def test_task_empty_or_whitespace_returns_422(monkeypatch, task):
    repo = StubRepository()
    with _client(monkeypatch, repository=repo) as client:
        resp = client.post("/task", json={"task": task})
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details["field"] == "task"
    # Nothing was persisted (the Agent never started).
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# 9.4 / 12.10 — task run invokes MCP tools + RAG, writes the task row, done ok:true
# --------------------------------------------------------------------------- #
def test_task_run_invokes_tools_and_rag_and_writes_task_row(monkeypatch):
    repo = StubRepository(saved_id=3)
    vector_store = FakeVectorStore(hits=make_query_hits(["manual.txt", "spec.txt"]))
    embeddings = FakeEmbeddings()

    with _client(monkeypatch, repository=repo, embeddings=embeddings, vector_store=vector_store) as client:
        resp = client.post("/task", json={"task": "summarize the ingested manuals"})

    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    types = [etype for (etype, _) in frames]
    assert types[-1] == "done"

    # The default plan invokes a tool, retrieves, and synthesizes — all four phases
    # appear in the progress stream (Requirement 9.4 + 9.7).
    phases = [data["phase"] for (etype, data) in frames if etype == "progress"]
    assert "tool_invocation" in phases
    assert "retrieval" in phases
    assert "answer_synthesis" in phases

    done = [data for (etype, data) in frames if etype == "done"][0]
    assert done["persistence"] == {"ok": True}
    assert done["sources"] == ["manual.txt", "spec.txt"]  # referenced documents
    assert any(t["tool"] == "word_count" and t["ok"] for t in done["tools_invoked"])
    assert done["step_limit_reached"] is False

    # The task history row was written (Requirement 12.10).
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.CAPSTONE
    assert isinstance(record, CapstoneTaskRecord)
    assert record.task_text == "summarize the ingested manuals"
    assert record.sources == ["manual.txt", "spec.txt"]
    assert any(t["tool"] == "word_count" for t in record.tools_invoked)
    assert record.step_limit_reached is False
    assert record.final_answer


def test_task_run_persistence_failure_flags_done_not_ok(monkeypatch):
    repo = StubRepository(should_fail=True)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.post("/task", json={"task": "do something"})
    assert resp.status_code == 200
    done = [data for (etype, data) in _parse_sse(resp.text) if etype == "done"][0]
    # The run still completed (the answer was streamed); persistence flags not-ok.
    assert done["persistence"]["ok"] is False
    assert isinstance(done["persistence"]["operation_id"], str) and done["persistence"]["operation_id"]


# --------------------------------------------------------------------------- #
# 9.8 — a failed MCP tool is surfaced and the run continues
# --------------------------------------------------------------------------- #
def test_failed_tool_surfaced_and_run_continues(monkeypatch):
    from app.agent import (
        PHASE_ANSWER_SYNTHESIS,
        PHASE_TOOL_INVOCATION,
        StepDecision,
        run_task_sse,
    )
    import asyncio

    repo = StubRepository()
    server = build_default_mcp_server()
    decisions = [
        StepDecision(phase=PHASE_TOOL_INVOCATION, tool="calculator", arguments={"expression": "not math"}),
        StepDecision(phase=PHASE_TOOL_INVOCATION, tool="word_count", arguments={"text": "a b"}),
        StepDecision(phase=PHASE_ANSWER_SYNTHESIS, answer="done"),
    ]

    frames: list[tuple[str, dict]] = []

    async def run():
        async for frame in run_task_sse(
            "task", mcp_server=server, retriever=None, repository=repo, decisions=decisions
        ):
            frames.append(parse_sse_frame(frame))

    asyncio.run(run())

    done = [data for (etype, data) in frames if etype == "done"][0]
    tools = done["tools_invoked"]
    # Both tools were attempted; the failed one is surfaced as failed, the run still
    # reached answer synthesis (Requirement 9.8).
    assert [(t["tool"], t["ok"]) for t in tools] == [("calculator", False), ("word_count", True)]
    assert done["answer"] == "done"
    assert done["step_limit_reached"] is False


# --------------------------------------------------------------------------- #
# 9.5 / 12.11 — ingestion confirms exactly the docs and writes the ingest row
# --------------------------------------------------------------------------- #
def test_ingest_documents_confirms_docs_and_writes_ingest_row(monkeypatch):
    repo = StubRepository(saved_id=4)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.post(
            "/documents",
            files=[
                ("documents", ("a.txt", b"hello world from doc a", "text/plain")),
                ("documents", ("b.txt", b"another document body here", "text/plain")),
            ],
        )
    assert resp.status_code == 200
    body = resp.json()
    # The confirmation names exactly the ingested documents (Property 25 / Req 9.5).
    assert [d["name"] for d in body["documents"]] == ["a.txt", "b.txt"]
    assert body["persistence"] == {"ok": True}

    # The ingest history row was written (Requirement 12.11).
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.CAPSTONE
    assert isinstance(record, CapstoneIngestRecord)
    assert record.documents == ["a.txt", "b.txt"]


def test_ingest_persistence_failure_flags_body_not_ok(monkeypatch):
    repo = StubRepository(should_fail=True)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.post(
            "/documents",
            files=[("documents", ("a.txt", b"content", "text/plain"))],
        )
    assert resp.status_code == 200
    body = resp.json()
    assert [d["name"] for d in body["documents"]] == ["a.txt"]
    assert body["persistence"]["ok"] is False
    assert body["persistence"]["operation_id"]


# --------------------------------------------------------------------------- #
# 9.10 — ingestion embeddings failure -> 502 identifying the failure
# --------------------------------------------------------------------------- #
def test_ingest_embeddings_failure_returns_502(monkeypatch):
    repo = StubRepository()
    embeddings = FakeEmbeddings(raise_on={0})  # first embed call raises
    with _client(monkeypatch, repository=repo, embeddings=embeddings) as client:
        resp = client.post(
            "/documents",
            files=[("documents", ("a.txt", b"some content to embed", "text/plain"))],
        )
    assert resp.status_code == 502
    assert "error" in resp.json()
    assert repo.saved == []  # nothing persisted on an ingestion failure


# --------------------------------------------------------------------------- #
# 9.5 — oversized document (>10 MB) -> 422 naming the document
# --------------------------------------------------------------------------- #
def test_oversized_document_returns_422(monkeypatch):
    from app.ingest import MAX_DOC_BYTES

    repo = StubRepository()
    oversized = b"x" * (MAX_DOC_BYTES + 1)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.post(
            "/documents",
            files=[("documents", ("big.txt", oversized, "text/plain"))],
        )
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details["field"] == "documents"
    assert details["document"] == "big.txt"
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# 13.1 / 13.3 — history list (merged, discriminated ids) + detail by string id
# --------------------------------------------------------------------------- #
def test_history_list_returns_discriminated_ids(monkeypatch):
    summaries = [
        HistorySummary(id="ingest:2", created_at=datetime(2026, 1, 3, tzinfo=timezone.utc), label="ingest: a.txt"),
        HistorySummary(id="task:5", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc), label="do a thing"),
    ]
    repo = _ReadRepo(summaries=summaries)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == ["ingest:2", "task:5"]
    assert all(item["project_id"] == "capstone" for item in body)


def test_history_list_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_list=True)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_history_detail_task_by_string_id(monkeypatch):
    record = CapstoneTaskRecord(
        task_text="analyze the manuals",
        final_answer="the answer",
        tools_invoked=[{"tool": "word_count", "ok": True, "error": None}],
        sources=["manual.txt"],
        step_limit_reached=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo = _ReadRepo(record=record)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history/task:5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "task:5"
    assert body["kind"] == "task"
    # The detail route passed the discriminated STRING id through (BUG-003).
    assert repo.requested_id == "task:5"
    assert body["inputs"]["task"] == "analyze the manuals"
    assert body["outputs"]["answer"] == "the answer"
    assert body["outputs"]["sources"] == ["manual.txt"]
    assert body["outputs"]["step_limit_reached"] is False


def test_history_detail_ingest_by_string_id(monkeypatch):
    record = CapstoneIngestRecord(
        documents=["a.txt", "b.txt"],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo = _ReadRepo(record=record)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history/ingest:2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "ingest:2"
    assert body["kind"] == "ingest"
    assert repo.requested_id == "ingest:2"
    assert body["outputs"]["documents"] == ["a.txt", "b.txt"]


def test_history_detail_unknown_id_404(monkeypatch):
    repo = _ReadRepo(record=None)  # get_record returns None for unknown/malformed ids
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history/task:999")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_history_detail_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_get=True)
    with _client(monkeypatch, repository=repo) as client:
        resp = client.get("/history/task:5")
    assert resp.status_code == 502
    assert "error" in resp.json()


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
    for name in ("LLM_API_KEY", "HF_TOKEN", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("DB_PORT", "5432")

    settings = config.load_settings(required=main_module.REQUIRED_ENV)
    assert settings.db_port == 5432
    assert settings.hf_token == "v"
