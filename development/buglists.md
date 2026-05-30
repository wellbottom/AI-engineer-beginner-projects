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
- **Update (Task 9 — web-agent service):** The web-agent service venv installed its full manifest cleanly on Python 3.14 with **no source build** — the editable `ai_shared` path dependency pulled the same cp314 wheel set proven in Tasks 3/4/5 (incl. `tavily-python-0.7.25`, `chromadb-1.5.9`, `openai-2.38.0`, `sqlalchemy-2.0.50`, `psycopg[binary]-3.3.4`) plus `fastapi-0.136.3` / `uvicorn-0.48.0` / `starlette-1.2.0` / `httpx-0.28.1` / `hypothesis-6.155.1` / `pytest-9.0.3`. `python -c "from app.main import app; from ai_shared.search import TavilySearch"` succeeds and the suite is green: **25 passed** (5 property tests at ≥100 iters — cap/citation/validation/zero-results/search-failure). The service imports the Tavily client only via `ai_shared.search.TavilySearch` (never the SDK directly), so no new direct dependency was added. **No 3.14 wheel gap.** Risk remains **Deferred**.

### BUG-005: `HistoryRepository.get_record(SUPPORT, id)` returns only the latest turn, not the full session
- **Status:** Open
- **Discovered:** 2026-01-?? (Task 8.9 — support-chatbot history detail endpoint)
- **Area:** packages/ai_shared/history.py (`HistoryRepository._get_chat_session`) consumed by services/support-chatbot
- **Branch:** feat/svc-support-chatbot
- **Edge case:** The chatbot history detail view (`GET /history/{id}`, Requirements 12.6/13.4) must show a session's **full** ordered turn list. The shared `HistoryRepository.get_record(ProjectId.SUPPORT, id)` intentionally returns a `ChatTurnRecord` carrying the session id plus only the **most recent** turn's `user_message`/`assistant_reply` (its docstring notes "the full turn list is available via the relationship for the detail view"). So a service relying solely on `get_record` cannot render the whole conversation.
- **Expected:** A reopened chatbot history record shows every persisted turn in order (Requirement 13.4).
- **Actual:** `get_record(SUPPORT, id)` exposes only the latest turn; the full `ChatSessionHistory.turns` relationship is not surfaced through any `ai_shared` method.
- **Workaround (this task, no `ai_shared` signature change):** The service adds a small **read helper** `app/history_read.py::get_session_detail(session_factory, session_pk)` that reuses the shared ORM models (`ChatSessionHistory` + its `turns` relationship) and the shared `sessionmaker` to return the full ordered turn list for the detail endpoint. `ai_shared` public signatures are unchanged; the service still uses `list_records(SUPPORT)` for the list view.
- **Regression test:** `services/support-chatbot/tests/test_durable_independence_db.py` (DB-backed, Property 36) asserts the full persisted turn list is retrievable; `tests/test_app_example.py` covers the detail endpoint's 404/502 paths with a stubbed reader.
- **Related requirement / property:** Requirements 12.6, 13.3, 13.4
- **Resolution:** Tracked as a follow-up enhancement to `ai_shared.history` — add a first-class `get_chat_session_turns(session_id|pk)` (or have `get_record(SUPPORT)` return the full turn list) so services need no local read helper. Until then the service-layer helper covers the gap without expanding `ai_shared` scope.

### BUG-007: Web-agent persistence policy — persist the no-sources answer, persist nothing on search failure (Req 12.7 "when an answer is produced")
- **Status:** Resolved (design decision documented; not a defect)
- **Discovered:** 2026-06-?? (Task 9.6/9.9 — web-agent `POST /ask` persistence)
- **Area:** services/web-agent/app/logic.py (`ask_sse` / `_persist_answer`)
- **Edge case:** Requirement 12.7 says to persist "when the Web_Agent produces an answer", but Requirement 6.5 (zero results → a "no relevant web sources found" response with no citations) and Requirement 6.6 (search failure/30s timeout → only an error, no answer, no citations) are both terminal outcomes that are NOT a synthesized answer. The spec does not explicitly state whether the zero-results response or a search-failure error is persisted, so a decision was needed to stay consistent with "an answer is produced".
- **Expected:** Consistent, documented persistence behavior across all three terminal outcomes.
- **Decision (implemented):** (1) A **synthesized answer** (≥1 result) is persisted with its citations (Requirement 12.7, the primary case). (2) The **zero-results** "no relevant web sources found" response IS a produced answer (it is streamed as `data` + terminal `done`), so it is persisted as a completed ask with an **empty** citation list — this keeps `GET /history` showing every ask the user actually received an answer for. (3) A **search failure / timeout** produces NO answer (only a terminal `error`), so **nothing** is persisted — there is no completed answer to record, matching Requirement 6.6 ("return only an error response"). A gateway failure mid-synthesis likewise persists nothing. The persistence-failure indication (Requirement 12.4) rides on the terminal `done` for the two persisted cases and never converts a successful stream into an `error`.
- **Regression test:** `services/web-agent/tests/test_app_example.py::test_zero_results_no_sources_answer` (asserts the no-sources answer is persisted with empty citations), `::test_search_failure_returns_error_no_answer` and `::test_gateway_failure_mid_synthesis_returns_error` (assert `repo.saved == []`), plus `::test_completion_writes_expected_web_agent_row_and_done_ok_true`.
- **Related requirement / property:** Requirements 6.5, 6.6, 12.7, 12.4; Properties 12, 13
- **Resolution:** Documented decision. If the user later wants search-failure errors recorded for audit, add a separate error-history table rather than persisting a `WebAgentRecord` with no answer (which would pollute the "answers" history list).

## Resolved bugs

### BUG-006: Postgres rejects NUL bytes (`\x00`) in persisted text — durable history silently dropped for such input
- **Status:** Resolved
- **Discovered:** 2026-05-30 (support-chatbot Property 36 — `tests/test_durable_independence_db.py`, run against the ephemeral PostgreSQL)
- **Area:** packages/ai_shared/history.py (`build_history_record`) — cross-cutting across ALL six services that persist user-supplied text
- **Branch:** feat/svc-support-chatbot
- **Edge case:** Any persisted TEXT field whose value contains a NUL byte (`\x00`). Hypothesis (Property 36) found the counterexample `pairs=[('0', '\x00')]` — an `assistant_reply` of `"\x00"`. PostgreSQL `text`/`varchar` columns cannot store `\x00`, so `INSERT` raises `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`. This is **not** chatbot-specific: the same failure hits any user-supplied text persisted by any service — playground prompt/response_text, web-agent question/answer + citation titles, deep-research topic/report title/intro/section bodies/conclusion/sub-questions, capstone task_text/tool errors/document names, etc.
- **Expected:** Durable history keeps everything (Requirement 12.2). A turn/record whose text contains `\x00` is persisted (with the NUL removed) and remains retrievable; normal (non-NUL) text round-trips byte-for-byte unchanged.
- **Actual (before fix):** The DB write raised `psycopg.DataError`; the Requirement 12.4 best-effort wrapper (`ai_shared.persistence.persist_record`) caught it, so the user-facing operation still succeeded but the record was flagged not-saved and **silently dropped** from durable history — undesirable for a "keep everything" system. Property 36's `assert outcome.ok is True` failed on the `\x00` counterexample.
- **Fix:** Sanitize NUL bytes out of every persisted TEXT field at the point of record construction in `ai_shared.history.build_history_record`. Added a small pure helper `_strip_nul(s: str) -> str` (removes `\x00`; a no-op for normal text), plus `_strip_nul_opt` for optional fields and `_sanitize_json` to recursively strip `\x00` from strings nested in the JSON-able payloads (citation url/title, report title/intro/section bodies/conclusion, sub-question text, tool name/error, document names). Applied once in `build_history_record` so all six projects are covered uniformly. **Image BYTEA (`ImageRecord.image_bytes`) is intentionally NOT sanitized** — it legitimately holds `0x00`; only its text fields (prompt/model/mime_type) are sanitized. Public signatures and behavior for non-NUL input are unchanged (normal text round-trips byte-for-byte). Rationale: sanitizing at construction keeps durable history intact (Requirement 12.2) instead of dropping records via the 12.4 wrapper, and is applied in one shared place for every service.
- **Regression test:** `packages/ai_shared/tests/test_history_record_sanitize.py` (new, pure unit tests) — asserts `build_history_record` strips `\x00` from representative TEXT fields across project types (playground prompt/response_text, chatbot user_message/assistant_reply incl. the exact `"\x00"` counterexample, web-agent answer + citation title, deep-research report body + nested text, capstone task_text + tool error + document name) while leaving normal text and image bytes (`0x00` preserved) unchanged; also covers `_strip_nul` directly. The DB-backed `services/support-chatbot/tests/test_durable_independence_db.py::test_discarding_session_leaves_persisted_records_unchanged` (Property 36) now PASSES unchanged — its `assert outcome.ok is True` holds because NUL is sanitized before the DB write; its persisted-content oracle was updated to expect the sanitized form (`_strip_nul`-applied pairs), not weakened. `packages/ai_shared/tests/test_history_record_property.py` (Property 33) spot-checks were updated to compare against `_strip_nul`/`_sanitize_json`-applied expected values, keeping the "exactly the required fields plus timestamp" structural assertion intact.
- **Related requirement / property:** support-chatbot Property 36 (Requirements 5.1, 12.6); Requirement 12.2 ("keep everything" / no expiry); Requirement 12.4 (best-effort write policy that previously masked the drop). Also touches Property 33 (Requirements 12.1, 12.5–12.11).
- **Resolution:** Fixed in `ai_shared.history.build_history_record` via `_strip_nul` / `_strip_nul_opt` / `_sanitize_json` (BYTEA left untouched). Verified against the ephemeral PostgreSQL (`TEST_DATABASE_URL=postgresql+psycopg://ai_test:ai_test_pw@localhost:55432/ai_history_test`): `packages/ai_shared` suite **112 passed, 0 failed** (DB-backed tests ran, not skipped); `services/support-chatbot` suite **31 passed, 0 failed** (Property 36 ran and passed). `getDiagnostics` clean on all changed files. Picked up by the support-chatbot venv automatically via the editable `ai_shared` path dependency.

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

### BUG-008: Deep Research decomposition that yields fewer than 3 sub-questions — clamp policy (Req 7.1 "no fewer than 3")
- **Status:** Resolved (design decision documented; not a defect)
- **Discovered:** 2026-06-?? (Task 10.2 — deep-research `clamp_subquestions`)
- **Area:** services/deep-research/app/logic.py (`clamp_subquestions`)
- **Edge case:** Requirement 7.1 requires the topic to be decomposed into **no fewer than 3 and no more than 10** sub-questions, but the decomposition is driven by the LLM, which can return any number (0, 1, 2, 3, 10, 11, many) and can return duplicate/blank entries. The `>10` case is unambiguous (truncate). The `<3` case is ambiguous: the service could (a) **pad** to 3 by fabricating sub-questions, or (b) **treat it as a decomposition failure** and error out. The spec does not say which.
- **Expected:** A deterministic, documented clamp rule whose "used" set is always in `[3, 10]` and is **distinct** (so Property 16's "one section per distinct sub-question" holds), without fabricating content not grounded in the LLM's actual decomposition.
- **Decision (implemented):** `clamp_subquestions(raw_list)` first **normalizes** the raw list (strip each entry, drop empty/whitespace-only entries, de-duplicate preserving first-seen order). Then:
  - **> 10 distinct** → **truncate** to the first 10 (preserving order). Returns a list of length 10.
  - **3..10 distinct** → returned unchanged.
  - **< 3 distinct** → **raise `LLMGatewayError`** (action `"topic decomposition"`, HTTP 502) identifying that decomposition produced fewer than 3 distinct sub-questions. We do **NOT** pad/fabricate, because invented sub-questions are not grounded in the LLM's decomposition and would degrade the report. In the SSE pipeline this surfaces as a terminal `error` frame (`stage: "decomposition"`) and **nothing is persisted** (no completed report). This keeps Property 15 true: the number of sub-questions *used* is always in `[3, 10]` (when `<3`, none are used — the pipeline errors before researching).
- **Regression test:** `services/deep-research/tests/test_subquestion_clamp_property.py` (Property 15, ≥100 iters) — asserts `>10`→length-10 distinct subset, `3..10`→unchanged, `<3`→raises `LLMGatewayError`; `tests/test_app_example.py` covers the pipeline terminal `decomposition` error + no-persistence path.
- **Related requirement / property:** Requirement 7.1; Property 15 (clamp), Property 16 (distinct sections).
- **Resolution:** Documented decision. If the user later prefers padding over erroring on `<3`, change `clamp_subquestions`'s `<3` branch to re-prompt the LLM for more sub-questions (preferred over fabrication) and update Property 15's oracle accordingly.
