# Customer Support Chatbot — User Guide

Step-by-step instructions for operating the Customer Support Chatbot through the
Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the Support Chatbot Backend_Service
   (port **8002**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **Support Chatbot** (the
   message icon). The frontend routes to the chat screen, establishes a session,
   and the breadcrumb reads `App / Support Chatbot`.

## Submit a Request

1. Type your support question into the message composer (1–4,000 characters).
2. Click **Send Message** (or press Enter; Shift+Enter inserts a line break) to
   send the message to the Support Chatbot Backend_Service. An empty or
   over-length message is rejected with a validation message and is not sent to the
   model.
3. To start over, use the new-session control; this clears the in-memory
   conversation while leaving the durable history intact.

## View the Response

1. The assistant reply streams into the conversation thread incrementally; a
   loading indicator is shown until the reply completes.
2. If your message falls outside the supported topics, the assistant returns a
   single reply stating the request is out of scope, and the conversation history
   is retained.
3. If the gateway is unavailable or times out (30s), a human-readable
   "temporarily unavailable" message is shown and the existing conversation is
   preserved.
4. Use the **History** toggle in the top bar to browse previously persisted
   sessions and reopen earlier conversations.
