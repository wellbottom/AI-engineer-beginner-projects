"""Alembic environment for the shared History_Store schema.

This is the single shared migration history for every mini-project's history
tables (Requirements 12.2, 12.3). It targets :data:`ai_shared.models.Base.metadata`
so ``--autogenerate`` sees every table, and it resolves the database URL at runtime
from :class:`ai_shared.config.Settings` (the root ``.env`` ``DB_*`` variables),
matching the services' connection approach rather than hardcoding a URL.

URL resolution order:

1. ``-x db_url=...`` passed on the Alembic command line (used by tests/CI to point
   at an ephemeral database), else
2. ``sqlalchemy.url`` in ``alembic.ini`` if set (normally blank), else
3. :attr:`ai_shared.config.Settings.database_url` built from the ``DB_*`` env vars.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ai_shared.config import load_settings
from ai_shared.models import Base

# Alembic Config object (values from alembic.ini).
config = context.config

# Configure Python logging from the ini file when present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support — every History_Store table.
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Resolve the database URL (CLI -x db_url, then ini, then Settings)."""
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_url"):
        return x_args["db_url"]

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    # Resolve from the root .env DB_* variables (same approach as the services).
    settings = load_settings(required=["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"])
    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
