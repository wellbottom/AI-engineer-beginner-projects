#!/bin/sh
# Shared container entrypoint for every Python Backend_Service.
#
# Requirement 11.2 / 12.3: each service applies the single shared Alembic
# migration history (packages/ai_shared) BEFORE serving uvicorn, so the
# History_Store schema is present/upgraded on every container start.
#
# The Dockerfile sets WORKDIR to the service directory (so `exec "$@"` starts
# uvicorn from a directory where `app.main:app` is importable). We capture that
# directory, cd into packages/ai_shared to run Alembic (its alembic.ini lives
# there and resolves the DB URL from the DB_* env vars via ai_shared.config),
# then return and exec the service command passed as CMD.
#
# Alembic is retried: under Docker Compose all six services start together once
# Postgres is healthy, so `alembic upgrade head` can momentarily race across
# services (or hit a Postgres that is accepting connections but still finishing
# init). `alembic upgrade head` is idempotent — a service that loses the race
# simply re-runs and finds the schema already at head. See development/buglists.md
# BUG-010.
set -e

APP_DIR="$(pwd)"

echo "[entrypoint] applying Alembic migrations (shared History_Store schema)..."
cd /app/packages/ai_shared

n=0
until alembic upgrade head; do
  n=$((n + 1))
  if [ "$n" -ge 10 ]; then
    echo "[entrypoint] ERROR: 'alembic upgrade head' failed after $n attempts" >&2
    exit 1
  fi
  echo "[entrypoint] alembic attempt $n failed (DB not ready or concurrent migration); retrying in 3s..." >&2
  sleep 3
done

echo "[entrypoint] migrations applied; starting service in ${APP_DIR}"
cd "$APP_DIR"
exec "$@"
