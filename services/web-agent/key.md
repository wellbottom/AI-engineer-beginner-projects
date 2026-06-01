# Ask the Web Agent — Key Concepts

How Ask the Web works internally.

## Operation Process

1. The user submits a question from the Shared_Frontend.
2. The Backend_Service validates the question (1–2,000 trimmed characters). Empty,
   whitespace-only, or over-length questions return a validation error and the
   Search_Provider is never queried.
3. The service queries the Search_Provider (Tavily) and retrieves up to 10 ranked
   web results.
4. If at least one result is returned, the question and the retrieved content are
   sent to the LLM_Client to synthesize an answer that streams over SSE; the answer
   carries at least one citation referencing a source URL from the results.
5. The produced answer (with citations) is persisted to the shared History_Store.
   A zero-result ask returns a "no sources" answer (no citations, no synthesis
   call) and is still persisted; a search failure persists nothing.

## Request/Response Flow

```
Shared_Frontend  ──POST /ask──▶  Web Agent Backend_Service (:8003)
                                    │  validate question
                                    ▼
                                Search_Provider (Tavily)  ── up to 10 results ──┐
                                    │                                           │
                                    ▼ (≥1 result)                               │
                                LLM_Client ──▶ LLM_Gateway (claude-opus-4.7) ◀──┘
                                    │  stream answer + citations
        SSE data/done/error  ◀──────┘
                                    │  on done
                                    ▼
                                History_Store (PostgreSQL)
```

The Shared_Frontend opens a POST-based SSE connection to `/ask`; the
Backend_Service streams the answer as `data` frames, ends with a `done` event
carrying the citations and persistence indication, or emits a terminal `error`
event identifying a search or synthesis failure.

## Core Mechanism

The core mechanism is **retrieval-augmented answering with citations**. Fresh web
results from the Search_Provider are passed as grounding context to the LLM_Client,
which synthesizes a direct answer and attributes it to source URLs taken from those
results. Server-Sent Events stream the answer incrementally. Zero-result and
search-failure paths are handled explicitly so the engine never fabricates
citations, and persistence happens after the answer completes.

## External Providers

This project depends on the following external providers:

- **Search_Provider** — the Tavily web search API used to retrieve ranked web
  results.
- **LLM_Gateway** — the OpenAI-compatible model gateway (`claude-opus-4.7`) that
  synthesizes the cited answer.

It does not depend on Vector_Store, Embeddings_Service, or Image_Provider.
