# Capstone Project

FastAPI Backend_Service for the **Capstone** mini-project (port **8006**).

## Purpose

The Capstone integrates the three core AI-engineering patterns into one
application: an **Agent** that plans and executes a submitted task in at most 25
steps using the LLM_Client, an in-process **MCP_Server** that exposes tools to the
Agent via a Model Context Protocol surface, and **RAG** retrieval that queries the
Vector_Store via the Embeddings_Service when the Agent decides retrieval is needed.
It also ingests user documents into the Vector_Store. The Agent run streams
step-level updates over SSE, the final response bundles the answer, the tools
invoked, and the source documents referenced, and each run is durably persisted to
the shared History_Store.

## Setup Steps

1. Open a terminal at the repository root and change into this service directory:
   `cd services/capstone`.
2. Create the isolated virtual environment: `python -m venv .venv`.
3. Install the dependencies (this pulls in `ai_shared` as a local editable path
   dependency, which provides the HF embeddings wrapper and the Chroma vector-store
   wrapper, plus FastAPI, Uvicorn, and `python-multipart` for file uploads):
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Ensure the single root `.env` defines `LLM_API_KEY`, `HF_TOKEN`, and the five
   `DB_*` variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`);
   the service aborts startup and names any that are missing.
5. Confirm the LLM_Gateway is reachable at the configured base URL
   (`http://localhost:3090/v1`).

## Run Command

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8006
```

Once running, the service exposes:

| Method | Path             | Purpose                                                                 |
| ------ | ---------------- | ----------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                         |
| GET    | `/tools`         | The MCP tools exposed to the Agent (discovery).                        |
| POST   | `/documents`     | Ingest uploads (≤ 10 MB each); store embeddings; confirm ingested docs. |
| POST   | `/task`          | Validate + stream the Agent run over SSE; persist the task run.         |
| GET    | `/history`       | Newest-first merged summaries of task runs + ingestions.                |
| GET    | `/history/{id}`  | A persisted record's full detail (discriminated string id; 404/502).    |

Run the tests with `.venv\Scripts\python -m pytest -q` (Hypothesis property tests
run at ≥ 100 iterations; the Agent loop and providers are injectable/mocked).
