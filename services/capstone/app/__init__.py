"""Capstone Backend_Service (port 8006).

The capstone mini-project combines the three core AI-engineering patterns into one
service (Requirement 9):

- **Agent** — plans and executes a submitted task as a sequence of at most 25 steps
  using the LLM_Client; on each step it decides whether to invoke an MCP tool,
  perform RAG retrieval, or synthesize the final answer.
- **MCP_Server** — exposes one or more tools to the Agent via the Model Context
  Protocol (here a minimal in-process MCP-style tool registry; see ``app/mcp.py``
  and buglists BUG-009).
- **RAG** — when the Agent decides retrieval is needed it queries the Vector_Store
  (Chroma) via the Embeddings_Service (Hugging Face) for up to the 5 most relevant
  document chunks and includes them in the LLM request; otherwise no chunks are
  retrieved or included.

Documents are ingested via ``POST /documents`` (≤10 MB each), tasks are run via
``POST /task`` (SSE), and both task runs and ingestions are durably persisted to
the shared History_Store and browsable via ``GET /history`` / ``GET /history/{id}``.
"""
