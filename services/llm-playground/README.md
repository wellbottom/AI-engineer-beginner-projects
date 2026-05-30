# LLM Playground service

FastAPI Backend_Service for the **LLM Playground** mini-project (port **8001**).
It streams an LLM response over SSE for a user-supplied prompt + parameters and
durably persists each completed run to the shared History_Store.

> Full Project_Docs (`README.md` / `guide.md` / `key.md` per the documentation
> model) are produced in Task 14. This file is a developer quick-start only.

## Endpoints

| Method | Path             | Purpose                                                      |
| ------ | ---------------- | ------------------------------------------------------------ |
| GET    | `/health`        | Liveness probe.                                              |
| POST   | `/generate`      | Validate + stream the generation over SSE; persist on done.  |
| GET    | `/history`       | Newest-first summaries of persisted runs.                    |
| GET    | `/history/{id}`  | Full persisted run (404 unknown id, 502 on retrieval error). |

## Setup (raw local)

```powershell
cd services/llm-playground
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency plus FastAPI,
Uvicorn, and `sse-starlette`. Configuration is read from the single root `.env`
(`LLM_API_KEY` plus the five `DB_*` variables are required — the service aborts
startup naming any that are missing).

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

## Test

```powershell
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at >= 100 iterations. DB-backed tests skip
cleanly when no PostgreSQL is reachable (set `TEST_DATABASE_URL` or the `DB_*`
variables to run them).
