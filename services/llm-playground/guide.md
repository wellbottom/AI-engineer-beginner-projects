# LLM Playground — User Guide

Step-by-step instructions for operating the LLM Playground through the
Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the LLM Playground Backend_Service
   (port **8001**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **LLM Playground** (the
   terminal icon). The frontend routes to the Playground screen and the breadcrumb
   reads `App / LLM Playground`.

## Submit a Request

1. (Optional) In **Model Architecture Override**, type a model identifier to use
   instead of the default `claude-opus-4.7`; leave it blank to use the default.
2. (Optional) Set the **system prompt** (up to 4,000 characters), the
   **temperature** (0.0–2.0), and the **maximum output tokens** (1–4,096).
3. Type your prompt (1–8,000 characters) into the main prompt box.
4. Click **Compile & Run Gateway Stream** (or press Cmd/Ctrl + Enter) to send the
   request to the Playground Backend_Service. Invalid parameters are rejected with
   a validation message and the request is not sent to the model.

## View the Response

1. While the model generates, the response streams into the output console
   token-by-token; a loading indicator is shown until the stream ends.
2. When the response completes, the reported token usage (prompt tokens, output
   tokens, total tokens) is displayed.
3. If the gateway returns an error, the partial content is replaced by a
   human-readable error message that identifies the failed action, and your input
   is retained.
4. Use the **History** toggle in the top bar to browse previously persisted runs
   and reopen any earlier result.
