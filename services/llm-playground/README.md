# LLM Playground

FastAPI Backend_Service for the **LLM Playground** mini-project (port **8001**).

## Purpose

The LLM Playground lets a learner experiment interactively with prompts and model
parameters against the LLM_Gateway, so they can see how inputs shape model output.
A user supplies a prompt (and optionally a system prompt, temperature, and a
maximum output-token count); the service validates the request, streams the model
response token-by-token over SSE, reports the token usage for the completed
response, and durably persists each completed run to the shared History_Store so it
can be reopened later.

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/llm-playground`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency plus FastAPI, Uvicorn, and `sse-starlette`):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `LLM_API_KEY` and the five `DB_*`
   variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`); the
   service aborts startup and names any that are missing.
5. Confirm the LLM_Gateway is reachable at the configured base URL
   (`http://localhost:3090/v1`).

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

Once running, the service exposes:

| Method | Path             | Purpose                                                      |
| ------ | ---------------- | ------------------------------------------------------------ |
| GET    | `/health`        | Liveness probe.                                              |
| POST   | `/generate`      | Validate + stream the generation over SSE; persist on done.  |
| GET    | `/history`       | Newest-first summaries of persisted runs.                    |
| GET    | `/history/{id}`  | Full persisted run (404 unknown id, 502 on retrieval error). |

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; DB-backed tests skip cleanly when no PostgreSQL is
reachable).
