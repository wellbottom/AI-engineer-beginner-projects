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

## Resolved bugs

_None yet._
