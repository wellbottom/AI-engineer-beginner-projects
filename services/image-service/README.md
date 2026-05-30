# Image Generation service

FastAPI Backend_Service for the **Image Generation** mini-project (port **8005**).
It validates a 1-1000 non-whitespace-character prompt, calls the Image_Provider
(Hugging Face via `huggingface_hub` `text_to_image`) with the selected model or a
default when none is selected, enforces a 60-second timeout, and on success returns
the generated image in a web-renderable PNG payload (`mime_type` + base64) the
Shared_Frontend can render directly. The completed generation is durably persisted
to the shared History_Store (the image stored as `BYTEA` bytes).

> Full Project_Docs (`README.md` / `guide.md` / `key.md` per the documentation
> model) are produced in Task 14. This file is a developer quick-start only.

## Endpoints

| Method | Path             | Purpose                                                                 |
| ------ | ---------------- | ----------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                         |
| GET    | `/models`        | The selectable model identifiers (default first).                       |
| POST   | `/generate`      | **Non-streamed**: validate + generate + persist; returns image JSON.    |
| GET    | `/history`       | Newest-first summaries of persisted generations.                        |
| GET    | `/history/{id}`  | A persisted generation's full record, re-emitting the stored PNG.       |

### `POST /generate` (non-streamed)

Accepts `{ "prompt": str, "model"?: str }`. The prompt is validated to have 1-1000
non-whitespace-trimmed characters (Requirement 8.6) before the provider is called;
the model defaults to `stabilityai/stable-diffusion-xl-base-1.0` when none is
selected (Requirement 8.3). On success it returns HTTP 200 with:

```json
{
  "mime_type": "image/png",
  "data_base64": "<base64 PNG>",
  "model": "<resolved model id>",
  "persistence": { "ok": true }
}
```

The frontend renders `data:<mime_type>;base64,<data_base64>` directly
(Requirement 8.2). The persistence indication is in the body (the endpoint is
non-streamed) — `{ "ok": false, "operation_id": "..." }` if the durable write
failed, while the image is still returned (Requirement 12.4).

Error responses (the shared `{ "error": { action, reason, details } }` envelope,
**no image data**):

- **provider error** → HTTP 502 including the provider reason (Requirement 8.5).
- **timeout** (no image within 60s) → HTTP 504, request cancelled (Requirement 8.7).
- **validation** → HTTP 422 identifying the violated prompt constraint
  (Requirement 8.6); the provider is never called.

## Provider isolation

`huggingface_hub` is reused transitively from the editable `ai_shared` install (it
already backs `ai_shared.embeddings.HFEmbeddings`) and is wrapped behind
`app/provider.py::HFImageProvider` — a lazy-import, injectable-client wrapper that
mirrors `ai_shared`'s provider-wrapper style. The wrapper converts the provider's
image to raw PNG bytes (Pillow), enforces the 60s timeout (`asyncio.wait_for` +
`asyncio.to_thread`, cancelling on expiry), and maps any provider error onto the
shared `ImageProviderError` / `ImageTimeoutError`. Tests inject a stub client, so
no network or HF token is needed.

## Setup (raw local)

```powershell
cd services/image-service
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency (which provides the
config, errors, History_Store models/repository incl. `ImageHistory` BYTEA, and the
`persist_record` wrapper, and pulls in `huggingface_hub` transitively) plus FastAPI,
Uvicorn, and Pillow. Configuration is read from the single root `.env` (`HF_TOKEN`
and the five `DB_*` variables are required — the service aborts startup naming any
that are missing). The image service does not use the LLM gateway or Tavily.

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8005
```

## Test

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://ai_test:ai_test_pw@localhost:55432/ai_history_test"
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at ≥ 100 iterations:

- **Property 22** — image prompt validation (1-1000 trimmed chars; failure names
  the constraint and skips the provider).
- **Property 20** — image encoding round-trip (web-renderable MIME type; decodes to
  exactly the original bytes).
- **Property 21** — provider error yields a reason and no image data (mocked
  provider driven through error/timeout outcomes).
- **Property 35** — persisted image bytes round-trip (DB-backed: persist then
  retrieve image bytes + MIME type, exact equality). Requires a reachable
  PostgreSQL (`TEST_DATABASE_URL`); skips cleanly otherwise.

The provider and the database are stubbed in the non-DB tests; Property 35 runs
against the ephemeral PostgreSQL.
