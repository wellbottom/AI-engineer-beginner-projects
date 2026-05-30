# Deep Research service

FastAPI Backend_Service for the **Deep Research** mini-project (port **8004**).
It validates a research topic, decomposes it into 3–10 sub-questions via the
LLM_Client, and for each sub-question queries the Search_Provider (Tavily) then
embeds and stores the retrieved source content in the Vector_Store (Chroma) via the
Embeddings_Service (Hugging Face) — streaming a `progress` event per completed
step. Only after every sub-question has been researched does it synthesize a
long-form, cited report (title, introduction, one section per sub-question,
conclusion) from the Vector_Store content via the LLM_Client, and durably persists
the completed report to the shared History_Store.

> Full Project_Docs (`README.md` / `guide.md` / `key.md` per the documentation
> model) are produced in Task 14. This file is a developer quick-start only.

## Endpoints

| Method | Path             | Purpose                                                              |
| ------ | ---------------- | -------------------------------------------------------------------- |
| GET    | `/health`        | Liveness probe.                                                      |
| POST   | `/research`      | Validate + stream the multi-step research over SSE; persist report.  |
| GET    | `/history`       | Newest-first summaries of persisted reports.                         |
| GET    | `/history/{id}`  | A persisted report's full record (404 unknown id, 502 retrieval err).|

`POST /research` accepts `{ "topic": str }`. The topic is validated to contain at
least one non-whitespace character (Requirement 7.8) before any decomposition or
search. The SSE stream emits one `progress` event per step in order:

1. **decomposition** — the topic is broken into 3–10 sub-questions.
2. **search** (per sub-question) — Tavily is queried for that sub-question.
3. **embedding** (per sub-question) — the retrieved content is embedded and stored
   in Chroma via the Embeddings_Service.
4. **synthesis** — only after all sub-questions are researched, the report is
   synthesized from the Vector_Store content (title, introduction, one section per
   sub-question with ≥1 citation per source-drawing section, conclusion).

The terminal `done` event carries the full report, the citations, the
sub-questions, and the persistence indication. Terminal `error` events:

- **decomposition** (`stage: "decomposition"`) — gateway failure/timeout, or the
  LLM produced fewer than 3 distinct sub-questions (see BUG-008); nothing persisted.
- **search** (`stage: "search"`) — a per-sub-question search failure naming **both**
  the search failure **and** the affected sub-question (Requirement 7.9); nothing
  persisted.
- **embedding / synthesis** (`stage: "embedding"`/`"synthesis"`) — an embeddings or
  vector-store failure identifying the embeddings failure (Requirement 7.7); nothing
  persisted.

## Sub-question clamp decision (BUG-008)

`clamp_subquestions(raw)` normalizes the LLM's decomposition (trim, drop blanks,
de-duplicate) and then keeps the result in `[3, 10]`: `> 10` distinct → truncate to
the first 10; `3..10` → unchanged; `< 3` distinct → **raise** (a decomposition
failure — sub-questions are never fabricated/padded). This keeps the number of
sub-questions *used* always between 3 and 10 (Requirement 7.1).

## Setup (raw local)

```powershell
cd services/deep-research
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `ai_shared` as a local editable path dependency (which provides the
Tavily search wrapper, the HF embeddings wrapper, and the Chroma vector-store
wrapper) plus FastAPI and Uvicorn. Configuration is read from the single root
`.env` (`LLM_API_KEY`, `TAVILY_API_KEY`, `HF_TOKEN`, and the five `DB_*` variables
are required — the service aborts startup naming any that are missing).

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8004
```

## Test

```powershell
.venv\Scripts\python -m pytest -q
```

Property-based tests (Hypothesis) run at ≥ 100 iterations. There are no DB-backed
property tests in this service; persistence is exercised through a stubbed
`HistoryRepository`, and the providers (Tavily, HF embeddings, Chroma) are stubbed.
