# Bug List — AI Engineer Practice Monorepo

This file is the single source of truth for every bug and tracked risk discovered during
implementation or testing. It is governed by `.kiro/steering/development-workflow.md`.

**Rules**
- Add an entry the moment a bug or risk is discovered (during analysis, implementation, or testing).
- A bug is only `Resolved` when its fix is merged and its regression test passes.
- If an edge case affects multiple parts of the codebase, log it once here and create follow-up tasks.
- Reference the bug ID in commit messages and PR descriptions.

**Status values:** `Open` · `In Progress` · `Resolved` · `Won't Fix` · `Deferred`

---

## Entry template (copy for each new bug)

```
### BUG-NNN: <short title>
- **Status:** Open
- **Discovered:** YYYY-MM-DD (task / context, e.g. "Task 2.2 — config validation")
- **Area:** <package/service/file, e.g. packages/ai_shared/config.py>
- **Branch:** fix/<short-name>
- **Edge case:** <the boundary/invalid/failure condition that triggers it>
- **Expected:** <what should happen>
- **Actual:** <what happens instead>
- **Regression test:** <test name/path that reproduces it; must fail before fix, pass after>
- **Related requirement / property:** <e.g. Requirement 3.9 / Property 32>
- **Resolution:** <commit/PR link + one-line summary; filled when Resolved>
```

---

## Active bugs

### BUG-001: pnpm workspace glob must exclude the Python `packages/ai_shared`
- **Status:** Deferred
- **Discovered:** 2025-01-08 (Task 1.1 — JS/TS workspace tooling)
- **Area:** pnpm-workspace.yaml
- **Branch:** feat/monorepo-scaffold
- **Edge case:** `packages/` will host BOTH a JS/TS package (`ts-config`) and a Python package (`ai_shared`, added in Task 2.1) that has no `package.json`. A broad `packages/*` glob would make pnpm scan `packages/ai_shared`; while pnpm currently warns-and-skips directories without a `package.json`, relying on that is fragile and could break installs on future pnpm versions.
- **Expected:** pnpm only manages real JS/TS packages; the Python package is invisible to pnpm/Turborepo (per design: "Python is intentionally outside their scope").
- **Actual:** Mitigated proactively — `pnpm-workspace.yaml` declares `apps/*` and the explicit `packages/ts-config` (not `packages/*`), matching tasks.md. No failure observed; `pnpm install` resolves 2 workspace projects with exit 0.
- **Regression test:** `pnpm -r list --depth -1` lists exactly the root and `@repo/ts-config` (no Python dir); `pnpm install` exits 0.
- **Related requirement / property:** Requirement 1.3, 1.5
- **Resolution:** Tracked. Revisit if additional JS/TS packages are added under `packages/` (add each explicitly, or use a glob plus an exclusion, rather than a bare `packages/*`).

### BUG-002: ai_shared dev venv runs on Python 3.14 while design fixes Python 3.11+
- **Status:** Deferred
- **Discovered:** 2026-01-?? (Task 2 — ai_shared config + error layer)
- **Area:** packages/ai_shared (dev venv + pyproject `requires-python`)
- **Branch:** feat/ai-shared-config
- **Edge case:** The local toolchain is Python 3.14.4, but the design fixes backends at "Python 3.11+". `pyproject.toml` declares `requires-python = ">=3.11"`, so 3.14 satisfies it, but a >=3.11 floor does not pin an upper bound. A future dependency added in later tasks (e.g. `psycopg` v3, `sqlalchemy`, `openai`, `huggingface_hub`, `chromadb`) may not yet publish a Python 3.14 wheel, which would break `pip install` in a service venv even though config+errors install cleanly today.
- **Expected:** Every service venv installs its full manifest without source-build failures on the chosen interpreter.
- **Actual:** For Task 2 there is NO problem — `python-dotenv 1.2.2`, `pytest 9.0.3`, and `hypothesis 6.155.0` all installed as wheels on 3.14 and the suite passes (23 passed). Logged proactively because heavier native-dependency tasks (3/4/5/11) are the likely first place a 3.14 wheel gap appears.
- **Regression test:** `pip install -e ".[test]"` in each service venv exits 0; `pytest` green. (Task 2: confirmed green.)
- **Related requirement / property:** Requirement 1.4 (one venv + one manifest per service); design "Python 3.11+".
- **Resolution:** Tracked. If a later task hits a missing 3.14 wheel, decide between (a) installing a 3.11/3.12 interpreter for the affected service venv, or (b) pinning a compatible dependency version — and record the decision here rather than silently working around it.
- **Update (Task 3 — LLM client):** First native-ish dependency added. `pip install "openai>=1.40"` resolved **`openai 2.38.0`** on Python 3.14 with native cp314 wheels for its transitive native deps (`jiter-0.15.0-cp314-cp314-win_amd64`, `pydantic-core-2.46.4-cp314-cp314-win_amd64`); `python -c "import openai; from openai import AsyncOpenAI"` succeeds and the full `ai_shared` suite (46 tests) is green. **No 3.14 wheel gap for `openai`.** As a defensive measure the `openai` import is isolated behind a lazy import in `ai_shared/llm_client.py` (and the underlying client is injectable), so `resolve_model`, SSE formatting, and stream-event handling stay importable/testable even if a future environment lacks an `openai` wheel. Risk remains **Deferred** (still no upper bound; `psycopg`/`chromadb`/`huggingface_hub` in Tasks 4/5/11 are the next wheel-gap candidates).
- **Update (Task 4 — persistence layer):** The two highest-risk native deps for this stack landed cleanly on Python 3.14. `pip install "sqlalchemy>=2.0" "psycopg[binary]>=3.1" alembic` resolved native cp314 wheels with **no source build**: `sqlalchemy-2.0.50-cp314-cp314-win_amd64`, `psycopg-3.3.4` (pure-python core) + `psycopg_binary-3.3.4-cp314-cp314-win_amd64` (the bundled libpq C extension), `greenlet-3.5.1-cp314-cp314-win_amd64`, plus `alembic-1.18.4`, `Mako-1.3.12`, `MarkupSafe-3.0.3-cp314`. `python -c "import sqlalchemy, psycopg, alembic"` succeeds (sqlalchemy 2.0.50 / psycopg 3.3.4 / alembic 1.18.4). **No 3.14 wheel gap for the persistence stack** — the `psycopg[binary]` extra was chosen (over `psycopg[c]`, which needs a local build toolchain, or pure-`psycopg`, which needs a system libpq) precisely because it ships a self-contained cp314 wheel. Risk remains **Deferred** (still no upper bound; `chromadb`/`huggingface_hub` in Tasks 5/11 are the remaining wheel-gap candidates).
- **Update (Task 5 — provider wrappers):** The flagged highest-risk dependency (`chromadb`, with its heavy native transitive tree) and `tavily-python` **both installed cleanly on Python 3.14 with NO source build**. `pip install "tavily-python>=0.5" "chromadb>=0.5"` resolved prebuilt cp314 (or pure-python / abi3) wheels for the entire tree, including the heavy natives: `chromadb-1.5.9`, `onnxruntime-1.26.0-cp314-cp314-win_amd64`, `tokenizers-0.23.1-cp310-abi3`, `grpcio-1.80.0-cp314-cp314-win_amd64`, `numpy-2.4.6-cp314-cp314-win_amd64`, `huggingface_hub-1.17.0`, `hf-xet-1.5.0-cp37-abi3`, `tiktoken-0.13.0-cp314-cp314`, `aiohttp-3.13.5-cp314-cp314`, plus `tavily-python-0.7.25` (pure-python). `python -c "import tavily, chromadb, huggingface_hub"` succeeds (chromadb 1.5.9 / huggingface_hub 1.17.0 / tavily-python 0.7.25). **No 3.14 wheel gap for the provider stack.** Full `ai_shared` suite green after adding the wrappers + tests: **90 passed, 12 skipped** (the 12 skips are the DB-backed history tests with no `TEST_DATABASE_URL`), incl. a real local-Chroma `PersistentClient` add→query round-trip in a tmp dir. As a defensive measure each third-party SDK (`tavily`, `huggingface_hub`, `chromadb`) is isolated behind a **lazy import** in its wrapper (`ai_shared/search.py`, `embeddings.py`, `vectorstore.py`) and the underlying client is **injectable**, so the normalization / capping / timeout / error-mapping logic stays importable and unit-testable even if a future environment lacks one of these wheels. Risk remains **Deferred** (still no upper bound; `huggingface_hub` is reused by the Task 11 image service — already proven importable here). With Tasks 3/4/5 all clearing on cp314, no wheel gap has materialized anywhere in the `ai_shared` dependency set.

## Resolved bugs

### BUG-004: Playground SSE uses StreamingResponse + ai_shared.sse (not sse-starlette)
- **Status:** Resolved
- **Discovered:** 2026-01-?? (Task 7.1/7.4 — LLM Playground service streaming layer)
- **Area:** services/llm-playground/app/main.py (`POST /generate`), services/llm-playground/requirements.txt
- **Branch:** feat/svc-llm-playground
- **Edge case:** The task hint suggested `sse-starlette`'s `EventSourceResponse` OR FastAPI `StreamingResponse` with the shared `ai_shared.sse` helpers. `EventSourceResponse` re-frames each yielded value as its own `data:` field, which would DOUBLE-encode frames that are already fully-formatted `event:`/`data:` strings produced by `ai_shared.sse.format_*` — corrupting the wire format the frontend SSE client (`apps/web/src/lib/api.ts`) parses.
- **Expected:** Exactly one SSE-formatting source of truth (`ai_shared.sse`) so every service emits an identical `event:`/`data:` wire format (design "SSE contract").
- **Actual:** Chose FastAPI `StreamingResponse(media_type="text/event-stream")` and yield the `ai_shared.sse` frame strings directly (no double encoding). `sse-starlette` is intentionally NOT a dependency; `requirements.txt` documents this. The frontend already splits on blank lines and parses `event:`/`data:` lines, so the format matches.
- **Regression test:** `services/llm-playground/tests/test_app_example.py::test_generate_relays_tokens_in_order` (and the persistence/error-frame tests) parse the raw SSE body with `ai_shared.sse.parse_sse_frame` and assert correct `data`/`done`/`error` frames — these would fail under double-encoding.
- **Related requirement / property:** Requirements 3.10, 4.4, 4.5, 4.6; design "SSE contract"
- **Resolution:** Deliberate, documented decision (not a defect). Task 15 (Docker/deployment) must NOT assume `sse-starlette` is installed for llm-playground; the service depends only on `fastapi`/`uvicorn` for serving plus the shared `ai_shared.sse` helpers. If a later service genuinely needs `EventSourceResponse`, it must format payloads as raw dicts, not pre-framed strings.


### BUG-003: Capstone history merges two tables into one id space (task vs ingest)
- **Status:** Resolved
- **Discovered:** 2026-01-?? (Task 4.3 — history.py HistoryRepository for the capstone project)
- **Area:** packages/ai_shared/history.py (`HistoryRepository.list_records` / `get_record` for `ProjectId.CAPSTONE`)
- **Branch:** feat/ai-shared-persistence
- **Edge case:** The capstone project persists into **two** tables — `capstone_task_history` (task runs, Requirement 12.10) and `capstone_ingest_history` (ingested documents, Requirement 12.11). Each table has its own independent `SERIAL` id sequence, so a task row and an ingest row can share the same numeric `id`. `list_records(CAPSTONE)` merges both tables (sorted newest-first by `created_at`) and `get_record(CAPSTONE, id)` looked up the task table first, then the ingest table. When a task row and an ingest row collide on `id` (e.g. both `id=1` after `TRUNCATE ... RESTART IDENTITY`), `get_record` always returned the task row for that id, hiding the ingest row of the same id.
- **Expected:** A history detail lookup unambiguously identifies a single capstone record regardless of which capstone sub-table it came from.
- **Actual (before fix):** `get_record(CAPSTONE, ingest_id)` returned the colliding `CapstoneTaskRecord` instead of the intended `CapstoneIngestRecord`, surfaced by `tests/test_history_repository_db.py::test_capstone_task_and_ingest_merged_newest_first` (`AttributeError: 'CapstoneTaskRecord' object has no attribute 'documents'`).
- **Regression test:** `tests/test_history_repository_db.py::test_capstone_numeric_id_collision_resolves_by_kind` — deliberately forces the numeric-id collision (task `id=1` and ingest `id=1` after `TRUNCATE ... RESTART IDENTITY`) and asserts `get_record` returns the correct KIND for each discriminated id, plus `None` for unknown/malformed capstone ids. (The existing `test_capstone_task_and_ingest_merged_newest_first` was also updated to assert the discriminated-id behavior.)
- **Related requirement / property:** Requirements 12.10, 12.11, 13.3
- **Resolution:** Fixed via a `kind`-discriminated capstone id (BUG-003's proposed scheme): `save_record` returns `"task:<n>"` / `"ingest:<n>"`, `list_records` sets each summary's id to that discriminated string (still merged + newest-first), and `get_record` parses the `"task:"`/`"ingest:"` prefix to select the correct table (returning `None` for unknown/malformed ids). `SavedId` was widened to `int | str`; the other five projects keep plain int ids unchanged. Regression test `test_capstone_numeric_id_collision_resolves_by_kind` now forces the collision and passes (full ai_shared suite green: 64 passed).
