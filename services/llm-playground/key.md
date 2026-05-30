# LLM Playground — Key Concepts

How the LLM Playground works internally.

## Operation Process

1. The user submits a prompt plus optional parameters (system prompt, temperature,
   maximum output tokens, model override) from the Shared_Frontend.
2. The Backend_Service validates every parameter (non-empty prompt ≤ 8,000 chars,
   system prompt ≤ 4,000 chars, temperature 0.0–2.0, max tokens 1–4,096). Invalid
   requests return a validation error naming the offending parameter and are never
   forwarded to the model.
3. The validated request is passed to the shared LLM_Client, which resolves the
   model (the override if provided, otherwise the default `claude-opus-4.7`) and
   forwards the temperature and max-token settings.
4. The model output is streamed back token-by-token over SSE as it arrives.
5. On completion the reported token usage is surfaced and the completed run is
   persisted to the shared History_Store.

## Request/Response Flow

```
Shared_Frontend  ──POST /generate──▶  LLM Playground Backend_Service (:8001)
                                          │  validate parameters
                                          ▼
                                      LLM_Client ──▶ LLM_Gateway (claude-opus-4.7)
                                          │  stream tokens
        SSE data/done/error  ◀───────────┘
                                          │  on done
                                          ▼
                                      History_Store (PostgreSQL)
```

The Shared_Frontend opens a POST-based SSE connection to `/generate`; the
Backend_Service relays each token from the LLM_Gateway as an SSE `data` frame, ends
with a `done` event carrying the usage and persistence indication, or emits a
terminal `error` event if the gateway fails.

## Core Mechanism

The core mechanism is **parameterized, streamed chat completion**. The service is a
thin, validated pass-through to the LLM_Gateway: it enforces the parameter bounds,
resolves the model identifier (override-else-default), maps frontend parameters to
the gateway request, and uses Server-Sent Events to deliver tokens incrementally so
the UI can render them as they are produced. Persistence happens after the stream
completes and never blocks the response.

## External Providers

This project depends on the following external providers:

- **LLM_Gateway** — the OpenAI-compatible model gateway (`claude-opus-4.7`) that
  produces the streamed completion.

It does not depend on Search_Provider, Vector_Store, Embeddings_Service, or
Image_Provider.
