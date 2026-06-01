# Image Generation Service

FastAPI Backend_Service for the **Image Generation Service** mini-project
(port **8005**).

## Purpose

The Image Generation Service turns a text description into an image. Given a 1–1000
character prompt and an optional model identifier, it calls the Image_Provider
(Hugging Face via `huggingface_hub`'s `text_to_image`) with the selected model or a
default, enforces a 60-second timeout, and returns the generated image as a
web-renderable PNG payload the Shared_Frontend can display directly. Each completed
generation is durably persisted to the shared History_Store (the image stored as
`BYTEA` bytes).

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/image-service`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency, which provides `huggingface_hub` transitively, plus FastAPI,
   Uvicorn, and Pillow):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `HF_TOKEN` and the five `DB_*` variables
   (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`); the service aborts
   startup and names any that are missing. This service does not use the LLM
   gateway or Tavily.

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8005
```

Once running, the service exposes:

| Method | Path             | Purpose                                                                 |
| ------ | ---------------- | ----------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                         |
| GET    | `/models`        | The selectable model identifiers (default first).                       |
| POST   | `/generate`      | **Non-streamed**: validate + generate + persist; returns image JSON.    |
| GET    | `/history`       | Newest-first summaries of persisted generations.                        |
| GET    | `/history/{id}`  | A persisted generation's full record, re-emitting the stored PNG.       |

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; the provider is stubbed, and the DB-backed Property 35
runs against an ephemeral PostgreSQL via `TEST_DATABASE_URL` and skips otherwise).
