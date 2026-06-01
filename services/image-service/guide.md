# Image Generation Service — User Guide

Step-by-step instructions for operating the Image Generation Service through the
Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the Image Service Backend_Service
   (port **8005**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **Image Service** (the
   image icon). The frontend routes to the image screen and the breadcrumb reads
   `App / Image Service`.

## Submit a Request

1. Type your image description into the prompt box (1–1000 characters).
2. (Optional) Choose an image-generation model from the model selector; if you
   leave it unset, the default model is applied.
3. Click **Generate Design Frame** to send the prompt to the Image Service
   Backend_Service. An empty, whitespace-only, or over-length prompt is rejected
   with a validation message and the provider is not called.

## View the Response

1. While the image is generated, a loading indicator is shown (the endpoint is
   non-streamed, so the image appears once when ready).
2. On success the generated image is rendered directly from the returned PNG
   payload, and you can export it.
3. If the provider returns an error, a human-readable message including the
   provider reason is shown and no image is displayed.
4. If no image is produced within 60 seconds, a timeout error is shown and no
   image is displayed.
5. Use the **History** toggle in the top bar to browse previously persisted
   generations and reopen earlier images.
