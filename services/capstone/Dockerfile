# Capstone Backend_Service (port 8006).
#
# Minimal/stub image — Task 15 finalizes the Docker deployment layer. The build
# context is expected to be the repo root so the shared package
# (packages/ai_shared) is available for the editable install.
#
#   docker build -f services/capstone/Dockerfile -t capstone .
FROM python:3.12-slim

WORKDIR /app

# Install the shared package first (better layer caching), then the service deps.
COPY packages/ai_shared /app/packages/ai_shared
COPY services/capstone/requirements.txt /app/services/capstone/requirements.txt

RUN pip install --no-cache-dir -r /app/services/capstone/requirements.txt

COPY services/capstone/app /app/services/capstone/app

WORKDIR /app/services/capstone

EXPOSE 8006

# Migrations (packages/ai_shared/migrations) are applied before serving in the
# deployment layer (Task 15); this CMD starts the ASGI server.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
