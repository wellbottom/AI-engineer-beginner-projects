"""Image Generation Backend_Service (port 8005).

A text-to-image service: it validates a 1-1000 non-whitespace-character prompt,
calls the Image_Provider (Hugging Face via ``huggingface_hub`` ``text_to_image``)
with the selected model or a default when none is selected, enforces a 60-second
timeout (cancel + timeout error, no image data), and on success returns the
generated image to the Shared_Frontend in a web-renderable PNG payload
(``mime_type`` + base64) it can display without further conversion. A provider
error yields an error response that includes the provider reason and no image data.

Unlike the streaming services, ``POST /generate`` is **non-streamed** — it returns
a single JSON body with the image data. On a successful image the service durably
persists a History_Record (prompt, selected model, the generated image stored as
``BYTEA`` bytes, MIME type, timestamp) via the shared best-effort ``persist_record``
wrapper, and returns the persistence indication in the JSON body as
``persistence: {ok, operation_id?}`` (Requirement 12.4). ``GET /history`` lists
persisted generations and ``GET /history/{id}`` re-emits the stored PNG as the same
web-renderable payload (Requirements 12.9, 13.1, 13.3). ``GET /models`` lists the
selectable model identifiers with a default.
"""
