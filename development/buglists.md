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

_None yet. Add entries as bugs are discovered._

## Resolved bugs

_None yet._
