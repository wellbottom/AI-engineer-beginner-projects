# Ask the Web Agent Backend_Service (port 8003) — Requirement 11.2.
#
# Build context MUST be the repo root so the shared package (packages/ai_shared)
# and the shared entrypoint (deploy/service-entrypoint.sh) are available:
#   docker build -f services/web-agent/Dockerfile -t web-agent .
# Under Docker Compose the build context/dockerfile are wired up for you.
#
# The container applies the single shared Alembic migration history
# (packages/ai_shared) BEFORE serving uvicorn (Requirements 11.2, 12.3) via the
# shared entrypoint, then serves the FastAPI app on this service's port.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Shared package first (better layer caching). It is the editable target of the
# service's `-e ../../packages/ai_shared` manifest line and also carries the
# Alembic migration history (alembic.ini + migrations/) applied at startup.
COPY packages/ai_shared /app/packages/ai_shared

# Shared entrypoint: runs `alembic upgrade head` (shared History_Store schema)
# before exec-ing the service CMD. `sed` strips any CRLF so the script runs under
# the slim image's /bin/sh regardless of the host checkout's line endings.
COPY deploy/service-entrypoint.sh /usr/local/bin/service-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/service-entrypoint.sh \
    && chmod +x /usr/local/bin/service-entrypoint.sh

# Install service deps from the service directory so the relative editable path
# (`-e ../../packages/ai_shared`) resolves to /app/packages/ai_shared.
WORKDIR /app/services/web-agent
COPY services/web-agent/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Service application code.
COPY services/web-agent/app ./app

EXPOSE 8003

# Apply migrations, then serve (uvicorn imports app.main:app from this WORKDIR).
ENTRYPOINT ["/usr/local/bin/service-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
