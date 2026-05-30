# Image Generation Service — Key Concepts

How the Image Generation Service works internally.

## Operation Process

1. The user submits a text prompt and an optional model identifier from the
   Shared_Frontend.
2. The Backend_Service validates the prompt (1–1000 trimmed, non-whitespace
   characters). Empty, whitespace-only, or over-length prompts return a validation
   error naming the violated constraint, and the Image_Provider is never called.
3. The model is resolved to the selected identifier, or the default when none is
   selected.
4. The service calls the Image_Provider (Hugging Face `text_to_image`) under a
   60-second timeout. On timeout the request is cancelled and a timeout error is
   returned; a provider error returns the provider reason with no image data.
5. On success the image is converted to PNG bytes and returned as a base64 payload
   with its MIME type, and the completed generation is persisted to the shared
   History_Store as `BYTEA` bytes.

## Request/Response Flow

```
Shared_Frontend  ──POST /generate──▶  Image Service Backend_Service (:8005)
                                          │  validate prompt + resolve model
                                          ▼
                                      Image_Provider (Hugging Face text_to_image)
                                          │  PNG bytes (≤ 60s, else timeout)
                                          ▼
                                      JSON { mime_type, data_base64, model, persistence }
        rendered image  ◀─────────────────┘
                                          │  on success
                                          ▼
                                      History_Store (PostgreSQL, BYTEA)
```

This endpoint is **non-streamed**: the Shared_Frontend issues a normal POST and
receives a single JSON response, then renders `data:<mime_type>;base64,<data>`
directly. The persistence indication is carried in the response body.

## Core Mechanism

The core mechanism is **bounded text-to-image generation with provider isolation**.
The provider SDK is wrapped behind a lazy-import, injectable client that converts
the provider's image to raw PNG bytes, enforces the 60-second timeout (cancelling
on expiry), and maps provider failures onto the shared error envelope. Because the
output is delivered as a self-contained base64 PNG, the frontend renders it without
further conversion, and persistence stores the exact bytes for later retrieval.

## External Providers

This project depends on the following external providers:

- **Image_Provider** — the Hugging Face image-generation capability accessed via
  the `huggingface_hub` library (`text_to_image`).

It does not depend on LLM_Gateway, Search_Provider, Vector_Store, or
Embeddings_Service.
