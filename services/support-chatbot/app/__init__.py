"""Customer Support Chatbot Backend_Service (port 8002).

Package layout mirrors the LLM Playground reference service (Task 7):

- :mod:`app.schemas` — request schema + the pure ``validate_message`` (Property 9).
- :mod:`app.session_store` — in-memory ``Session``/``Turn`` state + the pure
  ``append_turn`` history-trimming function and the 30-minute idle expiry
  (Properties 6, 36).
- :mod:`app.logic` — ``assemble_messages`` (Property 7), the out-of-scope
  classifier seam, and the ``chat_sse`` streaming + persistence generator
  (Properties 7, 8).
- :mod:`app.history_read` — a small service-layer reader for a session's full
  ordered turn list (BUG-005; no ``ai_shared`` signature change).
- :mod:`app.serialize` — JSON serialization for the history endpoints.
- :mod:`app.main` — the FastAPI wiring (startup config validation, lifespan,
  CORS, ``/health``, ``/chat``, ``/session``, ``/history``).
"""
