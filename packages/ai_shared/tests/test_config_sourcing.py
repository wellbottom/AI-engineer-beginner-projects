"""Unit tests for config sourcing, the committed ``.env.example``, and ``.gitignore``.

Covers:
- base URL / API key / model are read from the environment (Requirements 3.3, 3.6)
- defaults applied when optional vars are absent (Requirements 3.3, 3.4)
- ``database_url`` is built from the DB_* vars
- the committed root ``.env.example`` lists exactly the backend variable set,
  including DB_*, with placeholder (non-empty, non-secret) values (Requirements 3.2, 3.12)
- the root ``.gitignore`` excludes ``.env`` (Requirement 3.11)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import ai_shared.config as config
from ai_shared import Settings, load_settings


def test_llm_fields_read_from_env(monkeypatch: pytest.MonkeyPatch):
    """Base URL, API key, and model are sourced from the environment (3.3, 3.6)."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("LLM_MODEL", "some-other-model")

    s = load_settings(required=["LLM_API_KEY"])

    assert s.llm_base_url == "https://gw.example.test/v1"
    assert s.llm_api_key == "sk-test-123"
    assert s.llm_model == "some-other-model"


def test_defaults_applied_when_absent(monkeypatch: pytest.MonkeyPatch):
    """Defaults fill in optional vars when the environment omits them (3.3, 3.4)."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")

    s = load_settings(required=["LLM_API_KEY"])

    assert s.llm_base_url == "http://localhost:3090/v1"
    assert s.llm_model == "claude-opus-4.7"
    assert s.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert s.chroma_path == "./.chroma"


def test_database_url_built_from_db_vars(monkeypatch: pytest.MonkeyPatch):
    """``database_url`` uses the psycopg v3 URL shape from the DB_* vars (3.13)."""
    monkeypatch.setenv("DB_HOST", "db.example.test")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_USER", "appuser")
    monkeypatch.setenv("DB_PASSWORD", "s3cret")
    monkeypatch.setenv("DB_NAME", "history")

    s = load_settings(required=["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"])

    assert isinstance(s.db_port, int)
    assert s.db_port == 6543
    assert s.database_url == "postgresql+psycopg://appuser:s3cret@db.example.test:6543/history"


def test_db_port_default_when_absent(monkeypatch: pytest.MonkeyPatch):
    """DB_PORT defaults to 5432 when not required and not set."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    s = load_settings(required=["LLM_API_KEY"])
    assert s.db_port == 5432


def test_db_port_non_integer_raises(monkeypatch: pytest.MonkeyPatch):
    """A non-integer DB_PORT is surfaced as a configuration error (edge case)."""
    from ai_shared.errors import MissingConfigError

    monkeypatch.setenv("DB_HOST", "h")
    monkeypatch.setenv("DB_PORT", "not-a-number")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_NAME", "n")

    with pytest.raises(MissingConfigError) as exc:
        load_settings(required=["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"])
    assert "DB_PORT" in exc.value.names


# ── Committed .env.example and .gitignore checks ───────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]

# The complete backend-variable set the .env.example must document (Req 3.2, 3.12).
EXPECTED_ENV_KEYS = {
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "TAVILY_API_KEY",
    "HF_TOKEN",
    "EMBEDDING_MODEL",
    "CHROMA_PATH",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
}

# Tokens that would indicate a real secret rather than a placeholder.
_SECRET_PREFIXES = ("sk-", "hf_", "tvly-")


def _parse_env_keys(text: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        keys[name.strip()] = value.strip()
    return keys


def test_env_example_key_set_matches_backend_vars():
    """`.env.example` documents exactly the backend variable set incl. DB_* (3.2, 3.12)."""
    env_example = REPO_ROOT / ".env.example"
    assert env_example.is_file(), f"missing {env_example}"

    keys = _parse_env_keys(env_example.read_text(encoding="utf-8"))
    assert set(keys) == EXPECTED_ENV_KEYS

    # The variable set must align with what config.py knows about.
    assert set(keys) == set(config.KNOWN_ENV_VARS)


def test_env_example_has_placeholder_values_no_secrets():
    """Every documented var has a non-empty placeholder and no real secret (3.2, 3.12)."""
    env_example = REPO_ROOT / ".env.example"
    keys = _parse_env_keys(env_example.read_text(encoding="utf-8"))

    for name in EXPECTED_ENV_KEYS:
        value = keys[name]
        assert value, f"{name} should have a placeholder value"
        assert not value.startswith(_SECRET_PREFIXES), (
            f"{name} looks like a real secret, not a placeholder: {value!r}"
        )


def test_gitignore_excludes_env():
    """The root `.gitignore` excludes the secrets `.env` file (3.11)."""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.is_file(), f"missing {gitignore}"

    lines = {ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()}
    # A bare ``.env`` rule (or the ``.env.*`` family) must be present, while the
    # example files are re-included.
    assert ".env" in lines
    assert "!.env.example" in lines
