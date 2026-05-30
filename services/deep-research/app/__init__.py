"""Deep Research Backend_Service (port 8004).

A multi-step research engine: it validates a topic, decomposes it into 3–10
sub-questions via the LLM_Client, and for each sub-question queries the
Search_Provider (Tavily) then embeds and stores the retrieved source content in
the Vector_Store (Chroma) via the Embeddings_Service (Hugging Face), emitting a
``progress`` event per completed step. Only after every sub-question has been
researched does it synthesize a long-form report (title, introduction, one section
per sub-question, conclusion) from the Vector_Store content via the LLM_Client,
attaching citations drawn from the sources used in each section, and durably
persists the completed report to the shared History_Store.
"""
