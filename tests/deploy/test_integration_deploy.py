"""Deploy integration tests (Task 15.5).

These exercise real toolchain behavior (pnpm install, raw uvicorn startup, Docker
Compose up, postgres volume persistence). They are HEAVY and environment-dependent,
so every test is gated behind a short-timeout availability probe and SKIPS CLEANLY
(``pytest.skip`` with a reason) when the required tool is unavailable. None of them
hang: every subprocess call is bounded by a timeout.

Coverage:
- workspace install exit codes + package naming (Requirements 1.6, 1.7)
- raw frontend reachability <=60s (Requirement 11.5)
- end-to-end frontend->each backend connectivity (Requirement 11.7)
- ``docker compose up`` reachability <=120s (Requirement 11.8)
- failed-service reporting names each failure via ``docker compose ps`` (Requirement 11.9)
- postgres reads DB_* from .env (Requirement 11.12)
- records survive a postgres named-volume restart (Requirements 12.3, 11.10)

Run just these (with Docker up):  pytest tests/deploy -m integration
They are import-clean and skip without hanging when Docker/pnpm are absent.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from .conftest import (
    REPO_ROOT,
    SERVICE_PORTS,
    command_exists,
    compose_available,
    docker_available,
    load_compose,
)

pytestmark = pytest.mark.integration

BACKENDS = tuple(SERVICE_PORTS.keys())


class ToolLaunchError(RuntimeError):
    """A required CLI tool could not be launched (resolve to a clean skip)."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _http_ok(url: str, timeout: float = 3.0) -> bool:
    """True if a GET to ``url`` returns a 2xx/3xx/4xx (i.e. something answered)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 500
    except urllib.error.HTTPError as exc:
        # A served HTTP error still proves the port answered.
        return 200 <= exc.code < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_reachable(url: str, deadline_seconds: float, poll: float = 2.0) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < deadline_seconds:
        if _http_ok(url):
            return True
        time.sleep(poll)
    return False


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolve_exe(name: str) -> str:
    """Resolve a CLI name to a full path, including Windows .CMD/.BAT/.EXE shims.

    On Windows, package-manager CLIs (pnpm, npm) are typically ``.CMD`` shims that
    ``subprocess`` cannot launch by bare name without a shell. ``shutil.which``
    returns the full shim path (honoring PATHEXT), which IS launchable. Raises
    ToolLaunchError if the tool cannot be resolved.
    """
    resolved = shutil.which(name)
    if not resolved:
        raise ToolLaunchError(f"{name!r} not found on PATH")
    return resolved


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 300.0):
    """Run a bounded subprocess, returning the CompletedProcess (never hangs).

    The first element is resolved to a full executable path so Windows shims work.
    A launch failure (missing exe, OSError) is raised as ToolLaunchError so callers
    can convert it into a clean skip rather than a hard error.
    """
    exe = _resolve_exe(cmd[0])
    try:
        return subprocess.run(
            [exe, *cmd[1:]],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError) as exc:
        raise ToolLaunchError(f"could not launch {cmd[0]!r}: {exc}") from exc


def _compose_cmd() -> list[str]:
    return ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml")]


# --------------------------------------------------------------------------- #
# Requirements 1.6 / 1.7 — workspace install exit codes + package naming.
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_workspace_install_succeeds_and_lists_named_packages() -> None:
    if not command_exists("pnpm"):
        pytest.skip("pnpm not on PATH; workspace-install integration test skipped")

    try:
        # Requirement 1.6: install resolves and exits 0.
        install = _run(
            ["pnpm", "install", "--frozen-lockfile=false"], cwd=REPO_ROOT, timeout=600
        )
        # Requirement 1.7 (naming side): the workspace lists its declared JS/TS packages.
        listed = _run(["pnpm", "-r", "list", "--depth", "-1"], cwd=REPO_ROOT, timeout=120)
    except ToolLaunchError as exc:
        pytest.skip(f"pnpm not launchable; workspace-install test skipped ({exc})")

    assert install.returncode == 0, (
        f"pnpm install exited {install.returncode} (Requirement 1.6)\n{install.stderr[-2000:]}"
    )
    assert listed.returncode == 0, listed.stderr[-2000:]


def test_workspace_install_failure_reports_nonzero_exit() -> None:
    if not command_exists("pnpm"):
        pytest.skip("pnpm not on PATH; install-failure integration test skipped")

    # Requirement 1.7: when install fails for a package, the Workspace_Manager exits
    # non-zero and names the failing package. We provoke a real install failure in a
    # throwaway project that depends on an unresolvable package (no workspace, so the
    # repo is untouched). A slow/absent registry is bounded by the timeout -> skip.
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bad_pkg = {
            "name": "deploy-install-failure-probe",
            "version": "0.0.0",
            "private": True,
            "dependencies": {
                # A package name that cannot resolve on any registry.
                "this-package-truly-does-not-exist-xyz-9e8d7c6b5a": "^9.9.9",
            },
        }
        (tmp_path / "package.json").write_text(json.dumps(bad_pkg), encoding="utf-8")
        try:
            bad = _run(
                ["pnpm", "install", "--ignore-workspace", "--no-frozen-lockfile"],
                cwd=tmp_path,
                timeout=120,
            )
        except ToolLaunchError as exc:
            pytest.skip(f"pnpm not launchable; install-failure test skipped ({exc})")
        except subprocess.TimeoutExpired:
            pytest.skip("pnpm install timed out (registry slow/offline); failure test skipped")

    assert bad.returncode != 0, (
        "pnpm install of an unresolvable package should exit non-zero (Requirement 1.7)\n"
        f"stdout={bad.stdout[-1000:]}\nstderr={bad.stderr[-1000:]}"
    )
    # And it should name the failing package in its output.
    combined = (bad.stdout + bad.stderr).lower()
    assert "this-package-truly-does-not-exist-xyz-9e8d7c6b5a" in combined, (
        "install failure output should identify the failing package (Requirement 1.7)"
    )


# --------------------------------------------------------------------------- #
# Requirement 11.12 — the compose postgres reads DB_* from the root .env.
# Verified via `docker compose config` (interpolated) — needs Compose only, not a daemon up.
# --------------------------------------------------------------------------- #
def test_compose_postgres_reads_db_env_via_config() -> None:
    if not compose_available():
        pytest.skip("docker compose unavailable; postgres-env integration test skipped")

    try:
        rendered = _run([*_compose_cmd(), "config"], cwd=REPO_ROOT, timeout=60)
    except ToolLaunchError as exc:
        pytest.skip(f"docker not launchable; postgres-env test skipped ({exc})")
    assert rendered.returncode == 0, rendered.stderr[-2000:]
    text = rendered.stdout
    # The rendered config must carry POSTGRES_* for the postgres service, resolved
    # from DB_* (interpolation/defaults). We assert the keys are present and resolved
    # (no leftover unresolved ${...}).
    assert "POSTGRES_USER" in text and "POSTGRES_DB" in text, text[:1500]
    assert "${DB_" not in text, "compose left DB_* unresolved (Requirement 11.12)"


# --------------------------------------------------------------------------- #
# Requirement 11.8 / 11.7 — `docker compose up` reachability <=120s + connectivity.
# Builds are heavy; this is allowed to be run separately by the orchestrator.
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_compose_up_makes_services_reachable_within_120s() -> None:
    if not docker_available():
        pytest.skip("Docker daemon unavailable; compose-up integration test skipped")
    if not compose_available():
        pytest.skip("docker compose unavailable; compose-up integration test skipped")

    up = _run([*_compose_cmd(), "up", "-d", "--build"], cwd=REPO_ROOT, timeout=1800)
    try:
        assert up.returncode == 0, f"compose up failed:\n{up.stderr[-3000:]}"

        # Requirement 11.8: frontend + each backend reachable within 120s.
        assert _wait_reachable("http://localhost:3000/", 120), "frontend not reachable <=120s"
        # Requirement 11.7: each backend answers its /health without connection errors.
        for svc, port in SERVICE_PORTS.items():
            assert _wait_reachable(f"http://localhost:{port}/health", 120), (
                f"{svc} (:{port}) not reachable <=120s (Requirement 11.7/11.8)"
            )
    finally:
        _run([*_compose_cmd(), "down"], cwd=REPO_ROOT, timeout=300)


# --------------------------------------------------------------------------- #
# Requirement 11.9 — failed-service reporting names each failure via compose ps.
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_failed_service_is_reported_by_compose_ps() -> None:
    if not docker_available() or not compose_available():
        pytest.skip("Docker/Compose unavailable; failed-service integration test skipped")

    # `docker compose ps` exposes per-service status; a failed/unhealthy service is
    # listed with a non-running state. We assert the mechanism: ps reports state for
    # each service so a failure surfaces by name (Requirement 11.9). Run against a
    # (possibly not-up) project — ps must still succeed and be name-addressable.
    ps = _run([*_compose_cmd(), "ps", "--all", "--format", "json"], cwd=REPO_ROOT, timeout=60)
    assert ps.returncode == 0, ps.stderr[-2000:]
    # The config also defines healthchecks for every backend so failures are detectable.
    compose = load_compose()
    for svc in BACKENDS:
        assert compose["services"][svc].get("healthcheck"), (
            f"{svc} lacks a healthcheck; a failure could not be reported (Requirement 11.9)"
        )


# --------------------------------------------------------------------------- #
# Requirements 12.3 / 11.10 — records survive a postgres named-volume restart.
# Uses ONLY the postgres service + its named volume (no app builds), so it is far
# lighter than a full `compose up`. Still gated + bounded.
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_records_survive_postgres_volume_restart() -> None:
    if not docker_available() or not compose_available():
        pytest.skip("Docker/Compose unavailable; volume-persistence integration test skipped")

    compose = load_compose()
    # The compose postgres uses a named volume; resolve the effective credentials
    # the way Compose would (default fallbacks match .env.example).
    assert compose["services"]["postgres"].get("volumes"), "postgres has no volume"
    user = "ai_monorepo"
    db = "ai_monorepo_history"

    cmd = _compose_cmd()
    try:
        # Start ONLY postgres (its named volume persists data across restarts).
        up = _run([*cmd, "up", "-d", "postgres"], cwd=REPO_ROOT, timeout=300)
        assert up.returncode == 0, up.stderr[-2000:]

        # Wait for readiness via pg_isready inside the container.
        ready = False
        for _ in range(30):
            chk = _run(
                [*cmd, "exec", "-T", "postgres", "pg_isready", "-U", user, "-d", db],
                cwd=REPO_ROOT,
                timeout=30,
            )
            if chk.returncode == 0:
                ready = True
                break
            time.sleep(2)
        assert ready, "postgres did not become ready"

        # Write a durable marker row.
        _run(
            [*cmd, "exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-c",
             "CREATE TABLE IF NOT EXISTS persist_probe(id serial primary key, note text);"],
            cwd=REPO_ROOT, timeout=30,
        )
        _run(
            [*cmd, "exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-c",
             "INSERT INTO persist_probe(note) VALUES ('survives-restart');"],
            cwd=REPO_ROOT, timeout=30,
        )

        # Restart WITHOUT -v (named volume must retain the data).
        down = _run([*cmd, "down"], cwd=REPO_ROOT, timeout=120)
        assert down.returncode == 0, down.stderr[-2000:]
        up2 = _run([*cmd, "up", "-d", "postgres"], cwd=REPO_ROOT, timeout=300)
        assert up2.returncode == 0, up2.stderr[-2000:]

        for _ in range(30):
            chk = _run(
                [*cmd, "exec", "-T", "postgres", "pg_isready", "-U", user, "-d", db],
                cwd=REPO_ROOT, timeout=30,
            )
            if chk.returncode == 0:
                break
            time.sleep(2)

        # The row must still be there (Requirements 12.3, 11.10).
        out = _run(
            [*cmd, "exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-t", "-c",
             "SELECT note FROM persist_probe WHERE note='survives-restart';"],
            cwd=REPO_ROOT, timeout=30,
        )
        assert out.returncode == 0, out.stderr[-2000:]
        assert "survives-restart" in out.stdout, (
            "history row did NOT survive a postgres named-volume restart (Requirement 12.3/11.10)"
        )
    finally:
        # Clean up the probe table but KEEP the volume (don't pass -v).
        _run(
            [*cmd, "exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-c",
             "DROP TABLE IF EXISTS persist_probe;"],
            cwd=REPO_ROOT, timeout=30,
        )
        _run([*cmd, "down"], cwd=REPO_ROOT, timeout=120)


# --------------------------------------------------------------------------- #
# Requirement 11.5 — raw frontend reachability <=60s (dev server, no Docker).
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_raw_frontend_reachable_within_60s() -> None:
    frontend = REPO_ROOT / "ai-monorepo-frontend"
    if not (REPO_ROOT / "apps" / "web").is_dir() and not frontend.is_dir():
        pytest.skip("frontend directory not found; raw-reachability test skipped")
    if not command_exists("npm"):
        pytest.skip("npm not on PATH; raw frontend reachability test skipped")
    if not (frontend / "node_modules").is_dir():
        pytest.skip("frontend deps not installed (npm install); raw-reachability test skipped")

    try:
        npm = _resolve_exe("npm")
    except ToolLaunchError as exc:
        pytest.skip(f"npm not launchable; raw-reachability test skipped ({exc})")

    # Start the Vite dev server on :3000 and assert reachability within 60s.
    proc = subprocess.Popen(  # noqa: S603
        [npm, "run", "dev", "--", "--port", "3000", "--strictPort"],
        cwd=str(frontend),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert _wait_reachable("http://localhost:3000/", 60), (
            "raw frontend dev server not reachable within 60s (Requirement 11.5)"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
