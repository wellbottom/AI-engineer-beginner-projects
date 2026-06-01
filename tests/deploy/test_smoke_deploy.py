"""Deploy smoke tests (Task 15.4) — NO containers; these MUST pass now.

Validates the repository / persistence structure that deployment depends on:

- three top-level dirs ``apps/`` ``services/`` ``packages/`` (Requirement 1.5)
- exactly one Shared_Frontend app (Requirement 1.1)
- one directory per backend with ``app/`` + ``requirements.txt`` + ``Dockerfile`` (1.2)
- root ``pnpm-workspace.yaml`` + ``turbo.json`` present and referencing the JS/TS
  packages (Requirement 1.3)
- exactly one Python dependency manifest (``requirements.txt``) per service (1.4)
- a SINGLE root ``docker-compose.yml`` that PyYAML-parses and declares a ``postgres``
  service with a named volume (11.3, 11.10) plus a ``pgadmin`` service
- root ``.env`` / ``.env.example`` exist and config loads from the root ``.env`` (3.1)
- the capstone MCP_Server exposes >=1 tool (9.2)
- the shared Alembic migration history + entrypoint are present (deployment glue)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from .conftest import REPO_ROOT, SERVICE_PORTS, load_compose

pytestmark = pytest.mark.smoke

BACKENDS = tuple(SERVICE_PORTS.keys())


# --------------------------------------------------------------------------- #
# Requirement 1.5 — three top-level directories.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("top", ["apps", "services", "packages"])
def test_three_top_level_directories_exist(top: str) -> None:
    assert (REPO_ROOT / top).is_dir(), f"missing top-level directory: {top}/"


# --------------------------------------------------------------------------- #
# Requirement 1.1 — exactly one Shared_Frontend application.
# --------------------------------------------------------------------------- #
def _frontend_dirs() -> list[Path]:
    """Frontend app dirs = those with a vite config + package.json + index.html.

    The SPA currently lives at ``./ai-monorepo-frontend`` and Task 16 moves it to
    ``apps/web``; this detector finds it in either location and asserts there is
    exactly one.
    """
    candidates = [REPO_ROOT / "ai-monorepo-frontend"]
    apps_dir = REPO_ROOT / "apps"
    if apps_dir.is_dir():
        candidates += [p for p in apps_dir.iterdir() if p.is_dir()]

    found: list[Path] = []
    for d in candidates:
        has_vite = (d / "vite.config.ts").is_file() or (d / "vite.config.js").is_file()
        has_pkg = (d / "package.json").is_file()
        has_index = (d / "index.html").is_file()
        if has_vite and has_pkg and has_index:
            found.append(d)
    return found


def test_exactly_one_frontend_app() -> None:
    found = _frontend_dirs()
    assert len(found) == 1, f"expected exactly one frontend app, found: {found}"


# --------------------------------------------------------------------------- #
# Requirement 1.2 — one directory per backend, each with app/ + manifest + Dockerfile.
# --------------------------------------------------------------------------- #
def test_six_backend_service_directories_exist() -> None:
    services_dir = REPO_ROOT / "services"
    present = {
        p.name
        for p in services_dir.iterdir()
        if p.is_dir() and (p / "app").is_dir()
    }
    assert set(BACKENDS) <= present, f"missing backend dirs: {set(BACKENDS) - present}"
    assert len(BACKENDS) == 6


@pytest.mark.parametrize("svc", BACKENDS)
def test_backend_dir_has_app_manifest_and_dockerfile(svc: str) -> None:
    svc_dir = REPO_ROOT / "services" / svc
    assert (svc_dir / "app").is_dir(), f"{svc}: missing app/ package"
    assert (svc_dir / "app" / "main.py").is_file(), f"{svc}: missing app/main.py"
    assert (svc_dir / "requirements.txt").is_file(), f"{svc}: missing requirements.txt"
    assert (svc_dir / "Dockerfile").is_file(), f"{svc}: missing Dockerfile"


# --------------------------------------------------------------------------- #
# Requirement 1.4 — exactly ONE Python dependency manifest per service.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("svc", BACKENDS)
def test_exactly_one_python_manifest_per_service(svc: str) -> None:
    svc_dir = REPO_ROOT / "services" / svc
    manifests = [
        name
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
        if (svc_dir / name).is_file()
    ]
    assert manifests == ["requirements.txt"], (
        f"{svc}: expected exactly one manifest (requirements.txt), found {manifests}"
    )


# --------------------------------------------------------------------------- #
# Requirement 1.3 — pnpm workspace + Turborepo config referencing JS/TS packages.
# --------------------------------------------------------------------------- #
def test_pnpm_workspace_present_and_references_js_ts_packages() -> None:
    ws_path = REPO_ROOT / "pnpm-workspace.yaml"
    assert ws_path.is_file(), "missing root pnpm-workspace.yaml"
    data = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
    packages = data.get("packages") or []
    assert packages, "pnpm-workspace.yaml declares no packages"
    # Must reference the frontend apps and the shared ts-config JS/TS package.
    assert any("apps" in entry for entry in packages), packages
    assert any("ts-config" in entry or "packages" in entry for entry in packages), packages


def test_turbo_pipeline_present() -> None:
    turbo_path = REPO_ROOT / "turbo.json"
    assert turbo_path.is_file(), "missing root turbo.json"
    import json

    data = json.loads(turbo_path.read_text(encoding="utf-8"))
    # Turborepo v2 uses "tasks" (older used "pipeline"); accept either.
    pipeline = data.get("tasks") or data.get("pipeline")
    assert pipeline, "turbo.json has no tasks/pipeline"
    assert "build" in pipeline, "turbo.json pipeline missing a build task"


# --------------------------------------------------------------------------- #
# Requirement 11.3 / 11.10 — single Compose file, parses, postgres + named volume,
# pgadmin, all six backends + web.
# --------------------------------------------------------------------------- #
def test_single_root_compose_file_exists() -> None:
    matches = sorted(
        p.name
        for p in REPO_ROOT.iterdir()
        if p.is_file()
        and p.name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
    )
    assert matches == ["docker-compose.yml"], (
        f"expected exactly one root compose file (docker-compose.yml), found {matches}"
    )


def test_compose_pyyaml_parses_and_declares_expected_services() -> None:
    compose = load_compose()
    assert isinstance(compose, dict), "compose did not parse to a mapping"
    services = compose.get("services") or {}
    # web + six backends + postgres + pgadmin = 9 services.
    expected = {"web", "postgres", "pgadmin", *BACKENDS}
    assert expected <= set(services), f"compose missing services: {expected - set(services)}"


def test_compose_postgres_has_named_volume() -> None:
    compose = load_compose()
    postgres = compose["services"]["postgres"]
    # Top-level named volume declared.
    top_volumes = compose.get("volumes") or {}
    assert top_volumes, "compose declares no named volumes"
    # The postgres service mounts a NAMED volume (name:/path), not a bind mount.
    mounts = postgres.get("volumes") or []
    named_mounts = []
    for m in mounts:
        if isinstance(m, str) and ":" in m and not m.startswith((".", "/", "~")):
            vol_name = m.split(":", 1)[0]
            if vol_name in top_volumes:
                named_mounts.append(vol_name)
        elif isinstance(m, dict) and m.get("type") == "volume":
            named_mounts.append(m.get("source"))
    assert named_mounts, f"postgres has no named volume mount (Requirement 11.10): {mounts}"
    # The named volume targets the postgres data directory.
    assert any("/var/lib/postgresql/data" in str(m) for m in mounts), mounts


def test_compose_pgadmin_service_present_and_depends_on_postgres() -> None:
    compose = load_compose()
    pgadmin = compose["services"]["pgadmin"]
    assert "pgadmin" in (pgadmin.get("image") or ""), pgadmin.get("image")
    depends = pgadmin.get("depends_on")
    if isinstance(depends, dict):
        assert "postgres" in depends
    else:
        assert "postgres" in (depends or [])


@pytest.mark.parametrize("svc", BACKENDS)
def test_compose_backend_reads_env_and_waits_for_postgres(svc: str) -> None:
    compose = load_compose()
    service = compose["services"][svc]
    # Reads secrets from the root .env (Requirement 11.4).
    env_file = service.get("env_file")
    env_files = [env_file] if isinstance(env_file, str) else (env_file or [])
    assert ".env" in env_files, f"{svc} does not read the root .env via env_file"
    # Points at the compose postgres (DB_HOST=postgres).
    environment = service.get("environment") or {}
    assert environment.get("DB_HOST") == "postgres", f"{svc} DB_HOST is not 'postgres'"
    # Waits for postgres to be healthy.
    depends = service.get("depends_on") or {}
    assert "postgres" in depends, f"{svc} does not depend on postgres"
    if isinstance(depends, dict):
        assert depends["postgres"].get("condition") == "service_healthy", (
            f"{svc} does not wait for postgres service_healthy"
        )
    # Has a healthcheck so a failed service is reported by `docker compose ps` (11.9).
    assert service.get("healthcheck"), f"{svc} has no healthcheck"


def test_compose_postgres_credentials_come_from_db_env_vars() -> None:
    # Requirement 11.12: the postgres service's credentials are sourced from the
    # DB_* variables (Compose ${DB_*} interpolation), not hardcoded literals.
    raw = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for token in ("${DB_USER", "${DB_PASSWORD", "${DB_NAME"):
        assert token in raw, f"compose postgres does not interpolate {token}...}}"


def test_compose_web_build_context_caveat_documented() -> None:
    # Requirement 1.1 / BUG-011: the web build context points at the current SPA
    # location and the Task-16 relocation caveat is called out in the compose file.
    raw = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ai-monorepo-frontend" in raw, "web build context not set to current SPA location"
    assert "BUG-011" in raw or "Task 16" in raw, "missing build-context relocation caveat"


# --------------------------------------------------------------------------- #
# Requirement 3.1 — root .env / .env.example exist; config loads from root .env.
# --------------------------------------------------------------------------- #
def test_root_env_and_example_exist() -> None:
    assert (REPO_ROOT / ".env").is_file(), "missing root .env"
    assert (REPO_ROOT / ".env.example").is_file(), "missing root .env.example"


def test_env_example_lists_db_connection_variables() -> None:
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        assert var in example, f".env.example missing {var} (Requirement 3.12)"


def test_config_loads_from_root_env() -> None:
    # Requirement 3.1: ai_shared.config sources configuration from the root .env.
    from ai_shared.config import load_settings

    # No variables marked required -> always succeeds, sourcing values + defaults
    # from the root .env. A populated database_url proves the DB_* path resolves.
    settings = load_settings([])
    assert settings.database_url.startswith("postgresql+psycopg://"), settings.database_url
    # Default model is the design default unless overridden in .env.
    assert settings.llm_model, "llm_model should resolve to a value (default claude-opus-4.7)"


# --------------------------------------------------------------------------- #
# Requirement 9.2 — capstone MCP_Server exposes >=1 tool.
# mcp.py imports only stdlib, so it loads by file path even outside the capstone venv.
# --------------------------------------------------------------------------- #
def _load_capstone_mcp_module():
    mcp_path = REPO_ROOT / "services" / "capstone" / "app" / "mcp.py"
    assert mcp_path.is_file(), "missing services/capstone/app/mcp.py"
    spec = importlib.util.spec_from_file_location("capstone_mcp_smoke", mcp_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["capstone_mcp_smoke"] = module
    spec.loader.exec_module(module)
    return module


def test_capstone_mcp_exposes_at_least_one_tool() -> None:
    module = _load_capstone_mcp_module()
    server = module.build_default_mcp_server()
    tools = server.list_tools()
    assert len(tools) >= 1, "capstone MCP_Server exposes no tools (Requirement 9.2)"
    # Each tool has the MCP-shaped name + description.
    for tool in tools:
        assert tool.name, "MCP tool missing a name"
        assert tool.description, "MCP tool missing a description"


# --------------------------------------------------------------------------- #
# Deployment glue: shared Alembic migration history + entrypoint present.
# --------------------------------------------------------------------------- #
def test_shared_alembic_migration_history_present() -> None:
    ai_shared = REPO_ROOT / "packages" / "ai_shared"
    assert (ai_shared / "alembic.ini").is_file(), "missing packages/ai_shared/alembic.ini"
    versions = ai_shared / "migrations" / "versions"
    assert versions.is_dir(), "missing migrations/versions dir"
    migrations = list(versions.glob("*.py"))
    assert migrations, "no Alembic migration scripts found (shared History_Store schema)"


def test_shared_service_entrypoint_present() -> None:
    entry = REPO_ROOT / "deploy" / "service-entrypoint.sh"
    assert entry.is_file(), "missing deploy/service-entrypoint.sh"
    text = entry.read_text(encoding="utf-8")
    assert "alembic upgrade head" in text, "entrypoint does not apply Alembic migrations"
