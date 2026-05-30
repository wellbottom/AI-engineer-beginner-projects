# Ask the Web Agent

FastAPI Backend_Service for the **Ask the Web Agent** mini-project (port **8003**).

## Purpose

Ask the Web is a Perplexity-style answer engine. Given a question, it searches the
web through the Search_Provider (Tavily) for up to 10 ranked results, synthesizes a
direct answer from the retrieved content via the LLM_Client, and returns that answer
with at least one citation drawn from the sources used. The answer streams over SSE,
and each produced answer is durably persisted to the shared History_Store so it can
be reopened later.

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/web-agent`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency, which provides the Tavily search wrapper, plus FastAPI and Uvicorn):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `LLM_API_KEY`, `TAVILY_API_KEY`, and the
   five `DB_*` variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`,
   `DB_NAME`); the service aborts startup and names any that are missing.
5. Confirm the LLM_Gateway is reachable at the configured base URL
   (`http://localhost:3090/v1`).

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8003
```

Once running, the service exposes:

| Method | Path             | Purpose                                                             |
| ------ | ---------------- | ------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                     |
| POST   | `/ask`           | Validate + stream the cited answer over SSE; persist the answer.    |
| GET    | `/history`       | Newest-first summaries of persisted asks.                           |
| GET    | `/history/{id}`  | A persisted ask's full record (404 unknown id, 502 retrieval err).  |

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; persistence is exercised through a stubbed repository).
