"""LLM Playground Backend_Service (port 8001).

A FastAPI service that lets a user experiment with prompts and model parameters
against the shared LLM_Gateway, streaming the response over SSE and durably
persisting each completed run to the History_Store. It reuses the shared
``ai_shared`` package for configuration, the LLM client, SSE formatting, structured
errors, and persistence (Requirements 1.4, 4.x, 12.x, 13.x).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
