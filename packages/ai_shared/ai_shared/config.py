"""Shared configuration loading and startup validation for backend services.

This module loads the single root ``.env`` file (Requirement 3.1), exposes a
typed :class:`Settings` object (including the five Database connection variables,
Requirements 3.12/3.13), and validates that every variable a service declares as
required is present before the service serves any request (Requirement 3.9).

The validation contract (Property 32): ``load_settings`` succeeds **iff** no
required variable is absent; on failure it raises :class:`MissingConfigError`
whose ``names`` equal **exactly** the set of absent required variables (including
any missing ``DB_*`` variables).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

from .errors import MissingConfigError

__all__ = [
    "Settings",
    "load_settings",
    "ENV_FIELD_MAP",
    "DEFAULTS",
    "KNOWN_ENV_VARS",
]

# Mapping of environment variable name -> Settings field name.
# This is the single source of truth for which env vars map onto which field.
ENV_FIELD_MAP: dict[str, str] = {
    "LLM_BASE_URL": "llm_base_url",
    "LLM_API_KEY": "llm_api_key",
    "LLM_MODEL": "llm_model",
    "TAVILY_API_KEY": "tavily_api_key",
    "HF_TOKEN": "hf_token",
    "EMBEDDING_MODEL": "embedding_model",
    "CHROMA_PATH": "chroma_path",
    "DB_HOST": "db_host",
    "DB_PORT": "db_port",
    "DB_USER": "db_user",
    "DB_PASSWORD": "db_password",
    "DB_NAME": "db_name",
}

# Defaults applied when a variable is absent from the environment (Requirement 3.4
# default model, plus gateway base URL, embedding model, and chroma path).
DEFAULTS: dict[str, str] = {
    "LLM_BASE_URL": "http://localhost:3090/v1",
    "LLM_MODEL": "claude-opus-4.7",
    "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    "CHROMA_PATH": "./.chroma",
}

# The full universe of known backend environment variables.
KNOWN_ENV_VARS: tuple[str, ...] = tuple(ENV_FIELD_MAP.keys())


@dataclass
class Settings:
    """Typed view of the backend configuration sourced from the root ``.env``."""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    tavily_api_key: str
    hf_token: str
    embedding_model: str
    chroma_path: str
    # Database connection variables (Requirements 3.12, 3.13).
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    @property
    def database_url(self) -> str:
        """SQLAlchemy/psycopg connection URL for the History_Store.

        ``postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME``
        """
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def _find_root_env() -> str | None:
    """Locate the root ``.env`` by searching upward from the CWD to the repo root.

    A service started from its own directory (e.g. ``services/llm-playground``)
    still finds the single root ``.env``. Returns ``None`` when no ``.env`` exists
    (in which case only ``os.environ`` and :data:`DEFAULTS` are used).
    """
    found = find_dotenv(usecwd=True)
    return found or None


def _read_env(env_path: str | None) -> dict[str, str]:
    """Build the effective environment.

    Process environment (``os.environ``) takes precedence over values read from
    the ``.env`` file, matching standard ``dotenv`` "do not override real env"
    semantics. Only known variables are considered.
    """
    file_values: dict[str, str] = {}
    if env_path:
        # dotenv_values may yield ``None`` for bare keys; coerce to "".
        file_values = {k: (v if v is not None else "") for k, v in dotenv_values(env_path).items()}

    effective: dict[str, str] = {}
    for name in KNOWN_ENV_VARS:
        if name in os.environ:
            effective[name] = os.environ[name]
        elif name in file_values:
            effective[name] = file_values[name]
    return effective


def load_settings(required: list[str]) -> Settings:
    """Load settings from the root ``.env`` and validate required variables.

    Args:
        required: Environment variable names that this service requires. A
            variable counts as present only when it is set to a non-empty value
            (after the defaults below are applied). Duplicates and order are
            irrelevant — the requirement is treated as a set.

    Returns:
        A fully-populated :class:`Settings`.

    Raises:
        MissingConfigError: If any required variable is absent (empty/unset).
            ``names`` lists **exactly** the absent required variables, sorted for
            stable output (Requirements 3.9, 3.13; Property 32).
    """
    env_path = _find_root_env()
    values = _read_env(env_path)

    # Apply defaults for any variable not already provided with a non-empty value.
    for name, default in DEFAULTS.items():
        if not values.get(name):
            values[name] = default

    # Validate: every required name must resolve to a non-empty value.
    # Deduplicate required names (treated as a set) before checking.
    missing = sorted(
        {name for name in required if not (values.get(name) or "").strip()}
    )
    if missing:
        raise MissingConfigError(names=missing)

    # DB_PORT: coerce to int, defaulting to 5432 when absent/blank.
    raw_port = (values.get("DB_PORT") or "").strip()
    try:
        db_port = int(raw_port) if raw_port else 5432
    except ValueError:
        # A non-integer DB_PORT is a configuration error; surface it clearly.
        raise MissingConfigError(
            names=["DB_PORT"],
            reason=f"DB_PORT must be an integer, got {raw_port!r}",
        )

    return Settings(
        llm_base_url=values.get("LLM_BASE_URL", DEFAULTS["LLM_BASE_URL"]),
        llm_api_key=values.get("LLM_API_KEY", ""),
        llm_model=values.get("LLM_MODEL", DEFAULTS["LLM_MODEL"]),
        tavily_api_key=values.get("TAVILY_API_KEY", ""),
        hf_token=values.get("HF_TOKEN", ""),
        embedding_model=values.get("EMBEDDING_MODEL", DEFAULTS["EMBEDDING_MODEL"]),
        chroma_path=values.get("CHROMA_PATH", DEFAULTS["CHROMA_PATH"]),
        db_host=values.get("DB_HOST", ""),
        db_port=db_port,
        db_user=values.get("DB_USER", ""),
        db_password=values.get("DB_PASSWORD", ""),
        db_name=values.get("DB_NAME", ""),
    )
