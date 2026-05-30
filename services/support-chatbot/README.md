# Support Chatbot service

FastAPI Backend_Service for the **Customer Support Chatbot** mini-project
(port **8002**). It maintains an in-memory conversation session, streams the
assistant reply over SSE for a user message, and durably persists each completed
turn to the shared History_Store.

> Full Project_Docs (`README.md` / `guide.md` / `key.md` per the documentation
> model) are produced in Task 14. This file is a developer quick-start only.

## Endpoints

| Method | Path                | Purpose                                                              |
| ------ | ------------------- | ------------------------------------------------------------------- |
| GET    | `/health`           | Liveness probe.                                                     |
| POST   | `/session`          | Create a new in-memory session; returns `{ session_id }`.           |
| DELETE | `/session/{id}`     | Discard an in-memory session (durable history is unaffected).       |
| POST   | `/chat`             | Validate + stream the reply over SSE; persist the completed turn.   |
| GET    | `/history`          | Newest-first summaries of persisted sessions.                       |
| GET    | `/history/{id}`     | A session's full ordered turns (404 unknown id, 502 retrieval err). |

`POST /chat` accepts `{ "session_id": str, "message": str }`. The message is
validated to 1–4000 trimmed characters (Requirement 5.7) before any gateway call.
The reply streams as `data` frames terminated by a single `done` event (which
carries the persistence indication). An out-of-scope message yields a single
canned reply and a `done` event (no LLM call). A gateway refusal/timeout (30s)
yields a terminal `error` event ("temporarily unavailable") and preserves history.

## System prompt (Requirement 5.3)

The configurable support persona + supported-topics system prompt is loaded
**once at startup** and held for the process lifetime. Its source is resolved in
this precedence order (see `app/system_prompt.py`):

1. `SUPPORT_SYSTEM_PROMPT` — literal prompt text (env var).
2. `SUPPORT_SYSTEM_PROMPT_FILE` — path to a UTF-8 file whose contents are the prompt.
3. The bundled default file `app/support_system_prompt.txt`.
4. A hard-coded fallback persona.

The out-of-scope deny-list keywords can be tuned with the optional
`SUPPORT_OUT_OF_SCOPE_KEYWORDS` env var (comma-separated).

## Setup (raw local)

```powershell
cd services/support-chatbot
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency plus FastAPI and
Uvicorn. Configuration is read from the single root `.env` (`LLM_API_KEY` plus the
five `DB_*` variables are required — the service aborts startup naming any that
are missing).

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8002
```

## Test

```powershell
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at ≥ 100 iterations. The DB-backed property
(Property 36) skips cleanly when no PostgreSQL is reachable (set
`TEST_DATABASE_URL` or the `DB_*` variables to run it).
