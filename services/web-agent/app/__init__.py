"""Ask the Web Agent Backend_Service (port 8003).

A Perplexity-style answer engine: it validates a question, queries the
Search_Provider (Tavily) for up to 10 ranked web results, synthesizes an answer
from the retrieved content via the LLM_Client (streamed over SSE), attaches
citations drawn from the retrieved sources, and durably persists each produced
answer to the shared History_Store.
"""
