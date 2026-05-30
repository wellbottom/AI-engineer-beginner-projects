# Capstone Project — Key Concepts

How the Capstone (Agent + RAG + MCP) works internally.

## Operation Process

1. The user optionally ingests documents and then submits a task from the
   Shared_Frontend.
2. The Backend_Service validates the task (at least one non-whitespace character).
   An empty task returns a validation error and the Agent is not started.
3. The Agent plans and executes the task as a sequence of at most 25 steps using the
   LLM_Client. On each step it decides whether to invoke an MCP tool, perform RAG
   retrieval, or synthesize the final answer.
4. When the Agent decides retrieval is needed, it queries the Vector_Store via the
   Embeddings_Service for up to the 5 most relevant document chunks and includes
   them in the LLM request; otherwise no chunks are retrieved.
5. Step-level updates stream over SSE. On completion the response bundles the final
   answer, the MCP tools invoked (each flagged ok/failed), and the referenced
   source documents; a failed tool does not abort the run, and reaching the
   25-step limit returns the partial results with an indication.
6. The completed run (and each document ingestion) is persisted to the shared
   History_Store.

## Request/Response Flow

```
Shared_Frontend  ──POST /task──▶  Capstone Backend_Service (:8006)
                                     │  validate task
                                     ▼
                                  Agent loop (≤ 25 steps) ──▶ LLM_Client ──▶ LLM_Gateway
                                     │  per step, as decided:
                                     ├─▶ MCP_Server (in-process tools: word_count, calculator)
                                     └─▶ RAG: Embeddings_Service (HF) ──▶ Vector_Store (Chroma, top-5)
        SSE progress/done/error  ◀───┘
                                     │  on done
                                     ▼
                                 History_Store (PostgreSQL)

Shared_Frontend  ──POST /documents──▶  Embeddings_Service ──▶ Vector_Store  (ingestion)
```

The Shared_Frontend opens a POST-based SSE connection to `/task`; the
Backend_Service streams one `progress` event per executed step and ends with a
`done` event carrying the final answer, the invoked tools, the referenced sources,
the step-limit indication, and the persistence indication. Document ingestion uses
a separate non-streamed `POST /documents` call.

## Core Mechanism

The core mechanism is **an LLM-driven agent loop that combines MCP tool use and RAG
retrieval**. The Agent reasons step-by-step with the LLM_Client, choosing on each
step whether to call a tool exposed by the in-process MCP_Server, retrieve grounding
chunks from the Vector_Store via the Embeddings_Service, or synthesize the answer.
The MCP_Server is a minimal in-process MCP-style tool registry (it mirrors the MCP
`list_tools`/`invoke` surface) rather than an external provider, so it is not one
of the five external providers below. A bounded step count, failed-tool tolerance,
and Server-Sent Events for step-level observability complete the design;
persistence happens after the run.

## External Providers

This project depends on the following external providers:

- **LLM_Gateway** — the OpenAI-compatible model gateway (`claude-opus-4.7`) that
  drives the Agent's planning and answer synthesis.
- **Embeddings_Service** — the Hugging Face inference endpoint
  (`sentence-transformers/all-MiniLM-L6-v2`) used to embed documents and retrieval
  queries.
- **Vector_Store** — the local Chroma vector database queried for the most relevant
  document chunks during RAG retrieval.

It does not depend on Search_Provider or Image_Provider. (The in-process MCP_Server
is part of the Capstone itself, not one of these external providers.)
