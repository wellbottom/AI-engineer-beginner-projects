# Customer Support Chatbot — Key Concepts

How the Customer Support Chatbot works internally.

## Operation Process

1. The user creates (or reuses) a session and sends a message from the
   Shared_Frontend.
2. The Backend_Service validates the message (1–4,000 trimmed characters). Empty or
   over-length messages return a validation error and are never sent to the model.
3. The service checks the message against the configured supported-topics scope. An
   out-of-scope message yields a single canned "outside supported topics" reply
   with no model call, and the conversation history is retained.
4. For an in-scope message, the service sends the configured system prompt, the
   retained conversation history, and the new message to the LLM_Client.
5. The assistant reply is streamed back over SSE; on completion the turn is
   persisted to the shared History_Store. The in-memory session holds up to 50
   turns and is discarded after 30 minutes of inactivity, while the persisted
   record remains.

## Request/Response Flow

```
Shared_Frontend  ──POST /chat──▶  Support Chatbot Backend_Service (:8002)
                                     │  validate message + scope check
                                     ▼
                                 LLM_Client ──▶ LLM_Gateway (claude-opus-4.7)
                                     │  stream reply tokens
        SSE data/done/error  ◀───────┘
                                     │  on done
                                     ▼
                                 History_Store (PostgreSQL)
```

The Shared_Frontend opens a POST-based SSE connection to `/chat`; the
Backend_Service relays the assistant reply as SSE `data` frames, ends with a
`done` event carrying the persistence indication, or emits a terminal `error`
event ("temporarily unavailable") if the gateway refuses or times out (30s).

## Core Mechanism

The core mechanism is **persona-grounded, history-aware chat with scope
enforcement**. A system prompt loaded once at startup defines the assistant persona
and its set of supported topics; each turn appends the retained conversation
history so replies stay contextual. A scope check short-circuits out-of-scope
requests before any model call, and Server-Sent Events deliver the reply
incrementally. Persistence happens after the turn completes and never blocks the
response.

## External Providers

This project depends on the following external providers:

- **LLM_Gateway** — the OpenAI-compatible model gateway (`claude-opus-4.7`) that
  generates the assistant replies.

It does not depend on Search_Provider, Vector_Store, Embeddings_Service, or
Image_Provider.
