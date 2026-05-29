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

## Setup

_To be documented (see deployment task 15.3)._

## Raw startup

_To be documented (see deployment task 15.3): manual local startup commands for the
shared frontend and each backend service, plus local PostgreSQL install/connection and a
persistent local data directory for history._

## Docker startup

_To be documented (see deployment task 15.3): single Docker Compose orchestration that
builds and runs the frontend, every backend service, and the PostgreSQL database with a
persistent volume._

## Database / pgAdmin inspection

_To be documented (see deployment task 15.3): how to inspect the history database with
pgAdmin for both the raw and Docker startup layers._
