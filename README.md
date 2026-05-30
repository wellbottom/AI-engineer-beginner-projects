# AI Engineer Practice Monorepo

A single repository bundling six learning-oriented mini-projects for practicing
core AI Engineering skills. One shared frontend (a single Vite + React + TypeScript
+ Tailwind SPA) provides the UI for every mini-project, while each mini-project that
needs server-side logic has its own independent Python + FastAPI backend service.

## Mini-projects

1. **LLM Playground** — interactive prompt/parameter experimentation against an LLM.
2. **Customer Support Chatbot** — a domain-grounded conversational support assistant.
3. **Ask the Web Agent** — a Perplexity-style answer engine that searches the web and cites sources.
4. **Deep Research** — multi-step research that produces a long-form, cited report.
5. **Image Generation Service** — text-to-image generation via Hugging Face.
6. **Capstone** — an integrated application combining Agent, RAG, and MCP (Model Context Protocol).

## Repository layout

The repository is organized into three top-level code directories. All three exist
regardless of which mini-projects require a backend.

- **`apps/`** — frontend applications. Holds the single shared Vite + React + TypeScript
  + Tailwind SPA (`apps/web`) that serves the UI for all six mini-projects.
- **`services/`** — backend services. One isolated Python + FastAPI service per mini-project
  that needs server-side logic, each with its own virtual environment and dependency manifest.
- **`packages/`** — shared packages. Cross-cutting code reused across the monorepo, including
  the shared Python package (`ai_shared`: LLM client, config, errors, SSE, persistence) and
  shared JS/TS configuration (`ts-config`).

## Configuration

Backend secrets and configuration live in a single root `.env` file (gitignored). Copy the
committed template and fill in real values:

```bash
cp .env.example .env
```

The frontend's own build-time backend base URLs (`VITE_*`) live separately in
`apps/web/.env.local` (see `apps/web/.env.local.example`).

## Service ports

Each backend runs on its own fixed port; the frontend is served on `:3000`.

| Mini-project              | Service directory          | URL (raw + Docker)        |
| ------------------------- | -------------------------- | ------------------------- |
| Shared Frontend (SPA)     | `apps/web`*                | http://localhost:3000     |
| LLM Playground            | `services/llm-playground`  | http://localhost:8001     |
| Customer Support Chatbot  | `services/support-chatbot` | http://localhost:8002     |
| Ask the Web Agent         | `services/web-agent`       | http://localhost:8003     |
| Deep Research             | `services/deep-research`   | http://localhost:8004     |
| Image Generation Service  | `services/image-service`   | http://localhost:8005     |
| Capstone                  | `services/capstone`        | http://localhost:8006     |
| PostgreSQL (History_Store)| _Docker service `postgres`_| localhost:5432            |
| pgAdmin (Database_Manager)| _Docker service `pgadmin`_ | http://localhost:5050     |

> \* The SPA currently lives at `./ai-monorepo-frontend`; Task 16 relocates it to
> `apps/web`. See the build-context caveat in `docker-compose.yml` and
> `development/buglists.md` BUG-011.

There are two ways to run the system: a **raw startup** layer (everything started
manually) and a **Docker startup** layer (one `docker compose up`). Both are documented
below (Requirement 11.6).

## Raw startup

Start a local PostgreSQL, then each backend service, then the frontend. All commands are
run from the repository root unless noted. Windows PowerShell shown; on POSIX use
`source .venv/bin/activate` instead of the `Scripts\` path.

### 1. Configuration

```bash
cp .env.example .env   # then fill in real LLM_API_KEY / TAVILY_API_KEY / HF_TOKEN
```

The backends read all secrets and the `DB_*` connection variables from this single root
`.env` (Requirement 3.1). For raw startup set `DB_HOST=localhost` and `DB_PORT=5432` (the
defaults in `.env.example`).

### 2. Local PostgreSQL with a persistent data directory (Requirement 11.11)

Install PostgreSQL 16 locally (e.g. the EnterpriseDB installer on Windows, `brew install
postgresql@16` on macOS, or your distro's `postgresql-16` package). So that
**History_Records survive restarts**, initialize a persistent local data directory inside
the repo at `./.pgdata` (gitignored) and point the server at it:

```bash
# One-time: create a persistent cluster in ./.pgdata
initdb -D ./.pgdata

# Start the server against that data dir (keeps data across restarts)
pg_ctl -D ./.pgdata -l ./.pgdata/server.log start

# One-time: create the role + database matching your .env DB_* values
createuser ai_monorepo --pwprompt        # password -> DB_PASSWORD
createdb   ai_monorepo_history -O ai_monorepo
```

Because the cluster lives in `./.pgdata`, stopping and restarting PostgreSQL (or rebooting)
keeps every persisted History_Record (Requirement 11.11). The shared Alembic migration
history creates the schema; apply it once before starting the services:

```bash
cd packages/ai_shared
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
.venv\Scripts\alembic upgrade head        # creates all history tables
cd ../..
```

### 3. Each backend service

For **each** of the six services, create its venv, install its one manifest, and run
uvicorn on its port. Example for `llm-playground` (repeat for the others, changing the
directory and port):

```bash
cd services/llm-playground
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8001
cd ../..
```

| Service               | Run command (from the service directory)                          |
| --------------------- | ----------------------------------------------------------------- |
| llm-playground (8001) | `.venv\Scripts\python -m uvicorn app.main:app --port 8001`        |
| support-chatbot (8002)| `.venv\Scripts\python -m uvicorn app.main:app --port 8002`        |
| web-agent (8003)      | `.venv\Scripts\python -m uvicorn app.main:app --port 8003`        |
| deep-research (8004)  | `.venv\Scripts\python -m uvicorn app.main:app --port 8004`        |
| image-service (8005)  | `.venv\Scripts\python -m uvicorn app.main:app --port 8005`        |
| capstone (8006)       | `.venv\Scripts\python -m uvicorn app.main:app --port 8006`        |

Each service runs `load_settings(...)` at startup and aborts with the names of any missing
required variables (Requirement 3.9), so a service that starts is correctly configured.

### 4. Frontend dev server

```bash
cd ai-monorepo-frontend        # Task 16: becomes apps/web
cp .env.local.example .env.local   # set the six VITE_* base URLs (localhost:800x)
npm install
npm run dev -- --port 3000
```

The SPA becomes reachable at **http://localhost:3000 within 60 seconds** of running the dev
server (Requirement 11.5). With every backend running, opening the SPA and submitting a
request reaches each service without connection errors (Requirement 11.7).

## Docker startup

The entire system — frontend, all six backends, PostgreSQL (with a persistent named volume),
and pgAdmin — starts from the **single** `docker-compose.yml` (Requirement 11.3) with one
command (Requirement 11.6):

```bash
docker compose up --build
```

All secrets are read from the root `.env` (Requirement 11.4); the `postgres` service reads
its credentials from the `DB_*` variables (Requirement 11.12). Within ~120 seconds every
service is reachable (Requirement 11.8) at:

- Frontend SPA — http://localhost:3000
- LLM Playground — http://localhost:8001 · Support Chatbot — http://localhost:8002
- Web Agent — http://localhost:8003 · Deep Research — http://localhost:8004
- Image Service — http://localhost:8005 · Capstone — http://localhost:8006
- pgAdmin — http://localhost:5050

Useful commands:

```bash
docker compose config        # validate the compose file parses
docker compose ps            # show each service's status + health
docker compose logs -f web   # follow a service's logs
docker compose down          # stop & remove containers (KEEPS the pgdata volume)
docker compose down -v       # also REMOVE the pgdata volume (deletes all history)
```

The `postgres` service stores its data in the named volume **`pgdata`**, so
History_Records survive `docker compose down` followed by `docker compose up` and any
container restart (Requirements 11.10, 12.3). They are only deleted if you explicitly run
`docker compose down -v`. Health checks are configured for every service, so if one fails
to start it shows as `unhealthy`/`exited` in `docker compose ps` (Requirement 11.9).

## Database inspection (pgAdmin)

The history database can be inspected with **pgAdmin** (the Database_Manager) in both
startup layers (Requirement 11.13). Use the `DB_*` values from your `.env` (defaults:
user `ai_monorepo`, database `ai_monorepo_history`).

### Docker startup layer

1. Start the stack: `docker compose up --build`.
2. Open pgAdmin at **http://localhost:5050** and log in with
   `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` (from `.env`, or the defaults
   `admin@example.com` / `admin`).
3. **Add New Server** → **Connection** tab:
   - **Host name/address:** `postgres` (the Compose service name — pgAdmin and Postgres
     share the Compose network)
   - **Port:** `5432`
   - **Maintenance database:** your `DB_NAME` (default `ai_monorepo_history`)
   - **Username / Password:** your `DB_USER` / `DB_PASSWORD`
4. Browse **Servers → (your server) → Databases → ai_monorepo_history → Schemas → public →
   Tables** to view the history tables (e.g. `playground_history`, `chat_session_history`,
   `image_history`, `capstone_task_history`, …).

### Raw startup layer

1. Ensure the local PostgreSQL from the **Raw startup** section is running against `./.pgdata`.
2. Install pgAdmin locally (desktop app) **or** run only the pgAdmin container and point it at
   the host:

   ```bash
   docker compose up -d pgadmin    # pgAdmin alone, at http://localhost:5050
   ```

3. **Add New Server** → **Connection** tab:
   - **Host name/address:** `localhost` (desktop pgAdmin) or `host.docker.internal`
     (the pgAdmin container reaching the host's PostgreSQL on Windows/macOS)
   - **Port:** `5432`
   - **Maintenance database / Username / Password:** your `DB_NAME` / `DB_USER` /
     `DB_PASSWORD`
4. Browse the same **public** schema tables as above to inspect persisted History_Records.
