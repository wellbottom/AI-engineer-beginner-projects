# Capstone service

FastAPI Backend_Service for the **Capstone** mini-project (port **8006**). It
combines the three core AI-engineering patterns into one service (Requirement 9):

- **Agent** — plans and executes a submitted task as a sequence of at most 25 steps
  using the LLM_Client; on each step it decides whether to invoke an MCP tool,
  perform RAG retrieval, or synthesize the final answer.
- **MCP_Server** — exposes one or more tools to the Agent via the Model Context
  Protocol (a minimal in-process MCP-style tool registry; see BUG-009).
- **RAG** — when the Agent decides retrieval is needed it queries the Vector_Store
  (Chroma) via the Embeddings_Service (Hugging Face) for up to the 5 most relevant
  document chunks and includes them in the LLM request; otherwise no chunks are
  retrieved or included.

> Full Project_Docs (`README.md` / `guide.md` / `key.md`) are produced in Task 14.
> This file is a developer quick-start only.

## Endpoints

| Method | Path             | Purpose                                                                 |
| ------ | ---------------- | ----------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                         |
| GET    | `/tools`         | The MCP tools exposed to the Agent (discovery).                        |
| POST   | `/documents`     | Ingest uploads (≤10 MB each); store embeddings; confirm ingested docs.  |
| POST   | `/task`          | Validate + stream the Agent run over SSE; persist the task run.         |
| GET    | `/history`       | Newest-first merged summaries of task runs + ingestions.                |
| GET    | `/history/{id}`  | A persisted record's full detail (discriminated string id; 404/502).    |

`POST /task` accepts `{ "task": str }`. The task is validated to contain at least one
non-whitespace character (Requirement 9.9) before the Agent is started. The SSE
stream emits one `progress` event per executed step identifying the phase
(`planning` | `tool_invocation` | `retrieval` | `answer_synthesis`) and the step's
sequence position (Requirement 9.7). The terminal `done` event carries the final
answer, the list of MCP tools invoked (each flagged `ok`/failed), the referenced
source documents, the `step_limit_reached` indication, and the persistence
indication (Requirements 9.6, 9.8, 9.11, 12.10).

`POST /documents` accepts a multipart form with one or more `documents` files. Each
file is rejected with a 422 if it exceeds 10 MB (Requirement 9.5); on success the
JSON body names exactly the ingested documents (Property 25) plus the persistence
indication (Requirements 12.11, 12.4). An embeddings failure → 502 identifying the
ingestion failure (Requirement 9.10).

## MCP approach (BUG-009)

The MCP_Server is implemented as a **minimal in-process MCP-style tool registry**
(`app/mcp.py`) rather than a full MCP SDK transport: each tool has a `name`, a
`description`, and an `invoke(arguments)` method, and the `MCPServer` mirrors the MCP
server surface (`list_tools` / `invoke`). Two real, deterministic tools are
registered — `word_count` and `calculator` — so the Agent always has ≥1 tool
(Requirement 9.2). The decision and its rationale are recorded in
`development/buglists.md` (BUG-009). No MCP SDK is imported, so there is no extra
Python-3.14 wheel risk; the Agent depends only on the `list_tools` / `invoke`
surface, so swapping in a real SDK later touches only `app/mcp.py`.

## Capstone history ids (BUG-003)

Capstone persists into two independently sequenced tables (task runs + ingestions),
so its history ids are `kind`-discriminated **strings** (`"task:<n>"` /
`"ingest:<n>"`). `GET /history` returns those ids in its merged, newest-first
summaries and `GET /history/{id}` accepts the discriminated string id — unknown or
malformed ids → 404.

## Setup (raw local)

```powershell
cd services/capstone
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency (which provides the HF
embeddings wrapper and the Chroma vector-store wrapper) plus FastAPI, Uvicorn, and
`python-multipart` (for the file uploads). Configuration is read from the single root
`.env` (`LLM_API_KEY`, `HF_TOKEN`, and the five `DB_*` variables are required — the
service aborts startup naming any that are missing).

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8006
```

## Test

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://ai_test:ai_test_pw@localhost:55432/ai_history_test"
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at ≥100 iterations. The Agent loop and its
decision points are injectable/mocked, so the property tests are deterministic and
need no live LLM/HF/Chroma/network. Persistence in unit/property tests is exercised
through a stubbed `HistoryRepository`.
