# Web Agent service

FastAPI Backend_Service for the **Ask the Web Agent** mini-project (port **8003**).
It validates a question, queries the Search_Provider (Tavily) for up to 10 ranked
web results, synthesizes a cited answer from the retrieved content via the
LLM_Client (streamed over SSE), and durably persists each produced answer to the
shared History_Store.

> Full Project_Docs (`README.md` / `guide.md` / `key.md` per the documentation
> model) are produced in Task 14. This file is a developer quick-start only.

## Endpoints

| Method | Path             | Purpose                                                             |
| ------ | ---------------- | ------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                     |
| POST   | `/ask`           | Validate + stream the cited answer over SSE; persist the answer.    |
| GET    | `/history`       | Newest-first summaries of persisted asks.                           |
| GET    | `/history/{id}`  | A persisted ask's full record (404 unknown id, 502 retrieval err).  |

`POST /ask` accepts `{ "question": str }`. The question is validated to 1–2000
trimmed characters (Requirement 6.7) before any search. The behavior of the SSE
stream:

- **≥1 result** — the answer streams as `data` frames terminated by a single
  `done` event carrying at least one citation (each URL drawn from the retrieved
  results) plus the persistence indication.
- **Zero results** — a single canned "no relevant web sources found" `data` frame
  followed by a `done` event with an **empty** citation list (`no_sources: true`);
  the LLM is not called for synthesis (Requirement 6.5). The no-sources answer is
  still persisted.
- **Search failure / 30s timeout** — a terminal `error` event (`stage: "search"`)
  identifying the search failure, with no answer and no citations; nothing is
  persisted (Requirement 6.6).
- **Gateway failure mid-synthesis** — a terminal `error` event (`stage:
  "synthesis"`) carrying the gateway reason; nothing is persisted.

## Setup (raw local)

```powershell
cd services/web-agent
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency (which provides the
Tavily search wrapper) plus FastAPI and Uvicorn. Configuration is read from the
single root `.env` (`LLM_API_KEY`, `TAVILY_API_KEY`, and the five `DB_*` variables
are required — the service aborts startup naming any that are missing).

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8003
```

## Test

```powershell
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at ≥ 100 iterations. There are no DB-backed
property tests in this service; persistence is exercised through a stubbed
`HistoryRepository`.
