# Deep Research — Key Concepts

How Deep Research works internally.

## Operation Process

1. The user submits a research topic from the Shared_Frontend.
2. The Backend_Service validates the topic (at least one non-whitespace character).
   Empty or whitespace-only topics return a validation error and nothing is
   decomposed or searched.
3. The service decomposes the topic into 3–10 distinct sub-questions via the
   LLM_Client.
4. For each sub-question it queries the Search_Provider, then embeds the retrieved
   content with the Embeddings_Service and stores it in the Vector_Store, emitting a
   progress event after each step.
5. Only after every sub-question has been researched does the service synthesize the
   report (title, introduction, one section per sub-question, conclusion) from the
   Vector_Store content via the LLM_Client, with at least one citation on each
   source-drawing section.
6. The completed report is persisted to the shared History_Store.

## Request/Response Flow

```
Shared_Frontend  ──POST /research──▶  Deep Research Backend_Service (:8004)
                                         │  validate topic
                                         ▼
                                     LLM_Client ──▶ LLM_Gateway  (decompose topic)
                                         │  per sub-question:
                                         ├─▶ Search_Provider (Tavily)        (search)
                                         ├─▶ Embeddings_Service (HF) ──▶ Vector_Store (Chroma)
                                         ▼  after all sub-questions:
                                     Vector_Store ──▶ LLM_Client ──▶ LLM_Gateway (synthesize)
        SSE progress/done/error  ◀───────┘
                                         │  on done
                                         ▼
                                     History_Store (PostgreSQL)
```

The Shared_Frontend opens a POST-based SSE connection to `/research`; the
Backend_Service streams one `progress` event per completed step, ends with a `done`
event carrying the report, citations, sub-questions, and persistence indication, or
emits a terminal `error` event identifying the failed stage.

## Core Mechanism

The core mechanism is **multi-step retrieve-embed-synthesize research with a
vector store**. The topic is decomposed into sub-questions; each is researched by
web search and the results are embedded and stored in the Vector_Store, building a
corpus that grounds the final synthesis. Report construction is strictly deferred
until all sub-questions are researched, so the report is never partially built, and
Server-Sent Events stream step-level progress throughout. Persistence happens after
the report completes.

## External Providers

This project depends on the following external providers:

- **Search_Provider** — the Tavily web search API used per sub-question.
- **LLM_Gateway** — the OpenAI-compatible model gateway (`claude-opus-4.7`) used to
  decompose the topic and synthesize the report.
- **Embeddings_Service** — the Hugging Face inference endpoint
  (`sentence-transformers/all-MiniLM-L6-v2`) that converts retrieved content into
  embeddings.
- **Vector_Store** — the local Chroma vector database that stores and retrieves the
  embedded source content.

It does not depend on Image_Provider.
