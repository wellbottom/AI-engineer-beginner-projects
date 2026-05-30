# Customer Support Chatbot Backend_Service (port 8002).
#
# Minimal/stub image — Task 15 finalizes the Docker deployment layer. The build
# context is expected to be the repo root so the shared package
# (packages/ai_shared) is available for the editable install.
#
#   docker build -f services/support-chatbot/Dockerfile -t support-chatbot .
FROM python:3.12-slim

WORKDIR /app

# Install the shared package first (better layer caching), then the service deps.
COPY packages/ai_shared /app/packages/ai_shared
COPY services/support-chatbot/requirements.txt /app/services/support-chatbot/requirements.txt

RUN pip install --no-cache-dir -r /app/services/support-chatbot/requirements.txt

COPY services/support-chatbot/app /app/services/support-chatbot/app

WORKDIR /app/services/support-chatbot

EXPOSE 8002

# Migrations (packages/ai_shared/migrations) are applied before serving in the
# deployment layer (Task 15); this CMD starts the ASGI server.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
