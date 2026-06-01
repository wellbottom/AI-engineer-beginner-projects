"""Shared pytest fixtures for the ``ai_shared`` test suite.

These fixtures isolate the configuration tests from the developer's real shell
environment and from the real root ``.env`` file, so tests are deterministic and
never depend on whatever secrets happen to be present on the machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ai_shared.config as config

# Repo root: tests/ -> ai_shared/ -> packages/ -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all known backend env vars and disable real ``.env`` discovery.

    Every test starts from a clean slate: no known variable is set in the process
    environment, and ``load_settings`` will not read the real root ``.env``. Tests
    that need variables set them explicitly via ``monkeypatch.setenv``.
    """
    for name in config.KNOWN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Never read the real root .env during tests.
    monkeypatch.setattr(config, "_find_root_env", lambda: None)


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to the monorepo root (where ``.env.example`` lives)."""
    return REPO_ROOT
