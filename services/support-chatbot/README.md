# Customer Support Chatbot

FastAPI Backend_Service for the **Customer Support Chatbot** mini-project
(port **8002**).

## Purpose

The Customer Support Chatbot is a domain-grounded conversational assistant. It
answers user questions within a configured support persona and a defined set of
supported topics, declining politely when a request falls outside that scope. The
service keeps an in-memory active session (up to 50 turns, discarded after 30
minutes of inactivity), streams each assistant reply over SSE, and durably persists
each completed turn to the shared History_Store so conversations remain browsable
after the session ends.

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/support-chatbot`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency plus FastAPI and Uvicorn):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `LLM_API_KEY` and the five `DB_*`
   variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`); the
   service aborts startup and names any that are missing.
5. (Optional) Configure the support persona via `SUPPORT_SYSTEM_PROMPT`,
   `SUPPORT_SYSTEM_PROMPT_FILE`, or the bundled default, and tune the out-of-scope
   keywords with `SUPPORT_OUT_OF_SCOPE_KEYWORDS`. The system prompt is loaded once
   at startup.

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8002
```

Once running, the service exposes:

| Method | Path             | Purpose                                                             |
| ------ | ---------------- | ------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                     |
| POST   | `/session`       | Create a new in-memory session; returns `{ session_id }`.           |
| DELETE | `/session/{id}`  | Discard an in-memory session (durable history is unaffected).       |
| POST   | `/chat`          | Validate + stream the reply over SSE; persist the completed turn.   |
| GET    | `/history`       | Newest-first summaries of persisted sessions.                       |
| GET    | `/history/{id}`  | A session's full ordered turns (404 unknown id, 502 retrieval err). |

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; the DB-backed property skips cleanly when no PostgreSQL is
reachable).
