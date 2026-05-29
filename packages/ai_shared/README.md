# ai_shared

Shared Python backend layer for the **AI Engineer Practice Monorepo**. It is the
single home for cross-cutting concerns that every FastAPI service needs, so the
six services stay consistent (one config source, one error contract, one LLM
access layer, one persistence layer).

`ai_shared` is **not** managed by pnpm/Turborepo. It is a plain Python package
installed as a **local (editable) path dependency** into each service's own
`venv`. This keeps the monorepo rule of *one dependency manifest per service*
(Requirement 1.4) true while avoiding code duplication.

## What's here (Task 2: config + error layer)

| Module | Purpose |
| --- | --- |
| `ai_shared/config.py` | `Settings` dataclass + `load_settings(required)` — loads the root `.env` (searching upward to the repo root), applies defaults, and validates that every required variable is present. Includes the five `DB_*` Database variables and a `database_url` property. |
| `ai_shared/errors.py` | Framework-agnostic structured error hierarchy with HTTP-status mapping and a shared `{"error": {"action", "reason", "details"}}` JSON envelope. |

Later tasks add `llm_client.py`, `sse.py`, `db.py`, `models.py`, `history.py`,
provider wrappers, and the Alembic migration history.

## Configuration

`load_settings(required)` reads the single root `.env` (Requirement 3.1). The
process environment takes precedence over `.env` values. Defaults are applied for
optional variables:

| Variable | Default |
| --- | --- |
| `LLM_BASE_URL` | `http://localhost:3090/v1` |
| `LLM_MODEL` | `claude-opus-4.7` |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `CHROMA_PATH` | `./.chroma` |

A variable counts as **present** only when it resolves to a non-empty value. If
any name in `required` is absent, `load_settings` raises `MissingConfigError`
whose `names` list equals **exactly** the absent required variables (sorted),
including any missing `DB_*` variables (Requirements 3.9, 3.13).

```python
from ai_shared import load_settings

# A history-persisting service requires the DB_* variables too.
settings = load_settings(required=[
    "LLM_API_KEY",
    "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME",
])
print(settings.database_url)
# postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
```

## Development

This package is installed into each service `venv`. To work on it in isolation:

```powershell
# from packages/ai_shared
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest
```

Property-based tests use **Hypothesis** (minimum 100 iterations) and are tagged
`# Feature: ai-engineer-practice-monorepo, Property {n}: {text}`.
