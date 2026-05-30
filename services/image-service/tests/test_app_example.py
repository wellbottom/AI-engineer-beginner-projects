"""Unit/example tests for the Image Generation service (Task 11.9 + endpoints).

Covers, with a MOCKED provider (no network/token) and a stubbed/injected repository
via the FastAPI ``TestClient``:

- **12.9 write-on-completion** — a successful ``POST /generate`` writes the expected
  image history row (prompt, model, durable image bytes, MIME type) and the JSON
  body carries the web-renderable image + ``persistence: {ok: true}``.
- **12.4 persistence-failure indication** — with a repository whose ``save_record``
  raises :class:`PersistenceError`, ``POST /generate`` STILL returns the image
  result and the JSON body carries ``persistence: {ok: false, operation_id}``.
- **8.5 provider error / 8.7 timeout** — surfaced as the shared error envelope
  (502 / 504) with the provider reason and no image data.
- **8.6 validation** — empty / whitespace / >1000-char prompts -> 422 naming the
  constraint, and the provider is never called.
- **8.3 GET /models** — returns the selectable identifiers including the default.
- **13.1/13.3/12.9 history** — ``GET /history`` newest-first summaries;
  ``GET /history/{id}`` re-emits the stored PNG payload; unknown id -> 404; a
  retrieval failure -> 502.
- **3.9/3.13 startup config validation** names the missing variables.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import ai_shared.config as config
from ai_shared.errors import ImageProviderError, ImageTimeoutError, MissingConfigError, PersistenceError
from ai_shared.history import HistorySummary, ImageRecord, ProjectId

from app import main as main_module
from app.schemas import DEFAULT_MODEL, SELECTABLE_MODELS

from .conftest import TINY_PNG, FakeImageProvider, StubRepository


@contextmanager
def _client(monkeypatch, *, provider, repository):
    """A TestClient whose app.state.provider/repository are the supplied fakes.

    Sets dummy required env vars and disables real ``.env`` discovery so the startup
    lifespan's config validation passes without contacting any real provider/DB.
    """
    monkeypatch.setattr(config, "_find_root_env", lambda: None)
    for name in ("HF_TOKEN", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("DB_PORT", "5432")

    with TestClient(main_module.app) as client:
        main_module.app.state.provider = provider
        main_module.app.state.repository = repository
        yield client


class _ReadRepo:
    """Repository stub backing GET /history (list) and GET /history/{id} (detail)."""

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


# --------------------------------------------------------------------------- #
# 12.9 — write-on-completion + 12.4 persistence indication (ok: true)
# --------------------------------------------------------------------------- #
def test_generate_writes_expected_image_row_and_returns_image_with_persistence_ok(monkeypatch):
    provider = FakeImageProvider(image_bytes=TINY_PNG)
    repo = StubRepository(saved_id=7)
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "  a red bicycle  ", "model": DEFAULT_MODEL})

    assert resp.status_code == 200
    body = resp.json()

    # The body carries the web-renderable image (Requirement 8.2) ...
    assert body["mime_type"] == "image/png"
    assert base64.b64decode(body["data_base64"]) == TINY_PNG
    assert body["model"] == DEFAULT_MODEL
    # ... and the persistence indication is ok:true (Requirement 12.4).
    assert body["persistence"] == {"ok": True}

    # The provider saw the trimmed prompt + resolved model (Requirements 8.6/8.3).
    assert len(provider.calls) == 1
    assert provider.calls[0]["prompt"] == "a red bicycle"
    assert provider.calls[0]["model"] == DEFAULT_MODEL

    # The expected image history row was written (Requirement 12.9).
    assert len(repo.saved) == 1
    project, record = repo.saved[0]
    assert project is ProjectId.IMAGE
    assert isinstance(record, ImageRecord)
    assert record.prompt == "a red bicycle"
    assert record.model == DEFAULT_MODEL
    assert record.image_bytes == TINY_PNG  # durable bytes
    assert record.mime_type == "image/png"
    assert record.created_at is not None


def test_generate_without_model_uses_default(monkeypatch):
    provider = FakeImageProvider()
    repo = StubRepository()
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "a sunset"})
    assert resp.status_code == 200
    assert resp.json()["model"] == DEFAULT_MODEL
    assert provider.calls[0]["model"] == DEFAULT_MODEL


# --------------------------------------------------------------------------- #
# 12.4 — persistence failure: result still returned, persistence ok:false
# --------------------------------------------------------------------------- #
def test_generate_persistence_failure_still_returns_image_and_flags_not_ok(monkeypatch):
    provider = FakeImageProvider(image_bytes=TINY_PNG)
    repo = StubRepository(should_fail=True)  # save_record raises PersistenceError
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "a blue whale"})

    # The user-facing image result is STILL returned (not converted to an error).
    assert resp.status_code == 200
    body = resp.json()
    assert body["mime_type"] == "image/png"
    assert base64.b64decode(body["data_base64"]) == TINY_PNG
    # The persistence-failure indication rides in the body (Requirement 12.4).
    persistence = body["persistence"]
    assert persistence["ok"] is False
    assert isinstance(persistence["operation_id"], str) and persistence["operation_id"]


# --------------------------------------------------------------------------- #
# 8.5 / 8.7 — provider error / timeout -> shared error envelope, no image data
# --------------------------------------------------------------------------- #
def test_generate_provider_error_returns_502_with_reason_no_image(monkeypatch):
    provider = FakeImageProvider(raise_exc=ImageProviderError(reason="model is overloaded"))
    repo = StubRepository()
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "a castle"})

    assert resp.status_code == 502
    body = resp.json()
    assert "error" in body
    assert body["error"]["reason"] == "model is overloaded"
    # No image data anywhere in the error response.
    assert "data_base64" not in body and "mime_type" not in body
    assert "data_base64" not in body["error"]
    assert repo.saved == []


def test_generate_timeout_returns_504_with_reason_no_image(monkeypatch):
    provider = FakeImageProvider(
        raise_exc=ImageTimeoutError(reason="no image within 60 seconds")
    )
    repo = StubRepository()
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": "a galaxy"})

    assert resp.status_code == 504
    body = resp.json()
    assert body["error"]["reason"] == "no image within 60 seconds"
    assert "data_base64" not in body and "mime_type" not in body
    assert repo.saved == []


# --------------------------------------------------------------------------- #
# 8.6 — validation -> 422, provider never called
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "prompt",
    [
        "",  # empty
        "   ",  # whitespace-only
        "\t\n ",  # whitespace-only (other chars)
        "x" * 1001,  # exceeds 1000
    ],
)
def test_generate_invalid_prompt_returns_422_without_calling_provider(monkeypatch, prompt):
    provider = FakeImageProvider()
    repo = StubRepository()
    with _client(monkeypatch, provider=provider, repository=repo) as client:
        resp = client.post("/generate", json={"prompt": prompt})

    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details["field"] == "prompt"
    assert isinstance(details["constraint"], str) and details["constraint"]
    # The provider was NEVER contacted and nothing was persisted.
    assert provider.calls == []
    assert repo.saved == []


@pytest.mark.parametrize("prompt", ["a", "x" * 1000, "   " + "x" * 1000 + "   "])
def test_generate_boundary_prompt_lengths_accepted(monkeypatch, prompt):
    """A 1-char and a 1000-char (trimmed) prompt are accepted (boundaries)."""
    provider = FakeImageProvider()
    with _client(monkeypatch, provider=provider, repository=StubRepository()) as client:
        resp = client.post("/generate", json={"prompt": prompt})
    assert resp.status_code == 200
    assert len(provider.calls) == 1


# --------------------------------------------------------------------------- #
# 8.3 — GET /models returns selectable identifiers including a default
# --------------------------------------------------------------------------- #
def test_models_lists_selectable_identifiers_with_default_first(monkeypatch):
    with _client(monkeypatch, provider=FakeImageProvider(), repository=StubRepository()) as client:
        resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.json()
    assert isinstance(models, list) and models
    assert models == list(SELECTABLE_MODELS)
    # The default is present and listed first (Requirement 8.3).
    assert models[0] == DEFAULT_MODEL
    assert DEFAULT_MODEL in models


def test_health(monkeypatch):
    with _client(monkeypatch, provider=FakeImageProvider(), repository=StubRepository()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# 13.1 / 13.3 / 12.9 — history list + detail re-emits the stored PNG; 404; 502
# --------------------------------------------------------------------------- #
def test_history_list_newest_first(monkeypatch):
    summaries = [
        HistorySummary(id=2, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc), label="a cat"),
        HistorySummary(id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), label="a dog"),
    ]
    repo = _ReadRepo(summaries=summaries)
    with _client(monkeypatch, provider=FakeImageProvider(), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == ["2", "1"]
    assert all(item["project_id"] == "image" for item in body)


def test_history_list_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_list=True)
    with _client(monkeypatch, provider=FakeImageProvider(), repository=repo) as client:
        resp = client.get("/history")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_history_detail_reemits_stored_png(monkeypatch):
    record = ImageRecord(
        prompt="a mountain",
        model=DEFAULT_MODEL,
        image_bytes=TINY_PNG,
        mime_type="image/png",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo = _ReadRepo(record=record)
    with _client(monkeypatch, provider=FakeImageProvider(), repository=repo) as client:
        resp = client.get("/history/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "5"
    assert body["project_id"] == "image"
    assert body["inputs"] == {"prompt": "a mountain", "model": DEFAULT_MODEL}
    # The stored PNG is re-emitted as the same web-renderable payload (Req 12.9).
    assert body["outputs"]["mime_type"] == "image/png"
    assert base64.b64decode(body["outputs"]["data_base64"]) == TINY_PNG


def test_history_detail_unknown_id_404(monkeypatch):
    repo = _ReadRepo(record=None)  # get_record returns None
    with _client(monkeypatch, provider=FakeImageProvider(), repository=repo) as client:
        resp = client.get("/history/999")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_history_detail_retrieval_failure_502(monkeypatch):
    repo = _ReadRepo(raise_on_get=True)
    with _client(monkeypatch, provider=FakeImageProvider(), repository=repo) as client:
        resp = client.get("/history/5")
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
    for name in ("HF_TOKEN", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("DB_PORT", "5432")

    settings = config.load_settings(required=main_module.REQUIRED_ENV)
    assert settings.db_port == 5432
    assert settings.hf_token == "v"
