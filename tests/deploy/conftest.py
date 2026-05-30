"""Shared fixtures/helpers for the deploy tests (Tasks 15.4 + 15.5).

Provides:
- ``REPO_ROOT`` discovery (walks up until it finds ``docker-compose.yml``).
- pytest markers ``smoke`` and ``integration``.
- ``load_compose()`` — parse ``docker-compose.yml`` with PyYAML (Requirement 11.3).
- availability probes (``docker_available`` / ``compose_available`` / command-exists)
  used by the integration tests to SKIP CLEANLY when the toolchain is missing.

The smoke tests never launch a container; the integration tests are gated behind the
probes below with a short timeout so they never hang.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

# Repo root = the nearest ancestor containing docker-compose.yml.
_HERE = Path(__file__).resolve()


def _find_repo_root(start: Path) -> Path:
    for parent in [start, *start.parents]:
        if (parent / "docker-compose.yml").is_file():
            return parent
    # Fallback: two levels up (tests/deploy/ -> repo root).
    return start.parents[1]


REPO_ROOT = _find_repo_root(_HERE)

# The six backend services and their fixed ports (design + Dockerfiles).
SERVICE_PORTS: dict[str, int] = {
    "llm-playground": 8001,
    "support-chatbot": 8002,
    "web-agent": 8003,
    "deep-research": 8004,
    "image-service": 8005,
    "capstone": 8006,
}


def load_compose() -> dict:
    """Parse the single root ``docker-compose.yml`` with PyYAML (Requirement 11.3)."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    with compose_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def command_exists(name: str) -> bool:
    """True if ``name`` is on PATH."""
    return shutil.which(name) is not None


@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    """True if the Docker daemon answers a short-timeout ``docker info`` probe.

    Cached so repeated calls across tests do not re-probe. Never hangs: a 10s
    timeout bounds the probe and any failure/timeout returns False.
    """
    if not command_exists("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@functools.lru_cache(maxsize=1)
def compose_available() -> bool:
    """True if ``docker compose version`` works (Compose v2+ plugin)."""
    if not command_exists("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def compose() -> dict:
    return load_compose()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "smoke: fast structural checks, no containers")
    config.addinivalue_line(
        "markers",
        "integration: needs Docker/toolchain; skips cleanly when unavailable",
    )
    config.addinivalue_line(
        "markers",
        "slow: heavy integration (builds/Compose up); run separately by the orchestrator",
    )
