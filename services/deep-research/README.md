# Deep Research

FastAPI Backend_Service for the **Deep Research** mini-project (port **8004**).

## Purpose

Deep Research performs multi-step research on a topic and produces a long-form,
cited report. It decomposes the topic into 3–10 sub-questions, searches the web for
each via the Search_Provider, embeds and stores the retrieved content in the
Vector_Store using the Embeddings_Service, and only after every sub-question has
been researched synthesizes a structured report (title, introduction, one section
per sub-question, conclusion) with citations via the LLM_Client. Progress streams
over SSE step-by-step, and the completed report is durably persisted to the shared
History_Store.

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/deep-research`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency, which provides the Tavily search wrapper, the HF embeddings wrapper,
   and the Chroma vector-store wrapper, plus FastAPI and Uvicorn):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `LLM_API_KEY`, `TAVILY_API_KEY`,
   `HF_TOKEN`, and the five `DB_*` variables (`DB_HOST`, `DB_PORT`, `DB_USER`,
   `DB_PASSWORD`, `DB_NAME`); the service aborts startup and names any that are
   missing.
5. Confirm the LLM_Gateway is reachable at the configured base URL
   (`http://localhost:3090/v1`).

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8004
```

Once running, the service exposes:

| Method | Path             | Purpose                                                              |
| ------ | ---------------- | -------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                      |
| POST   | `/research`      | Validate + stream the multi-step research over SSE; persist report.  |
| GET    | `/history`       | Newest-first summaries of persisted reports.                         |
| GET    | `/history/{id}`  | A persisted report's full record (404 unknown id, 502 retrieval err).|

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; the providers and persistence are stubbed).
