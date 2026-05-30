# Capstone Project — User Guide

Step-by-step instructions for operating the Capstone through the Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the Capstone Backend_Service
   (port **8006**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **Capstone Agent** (the
   briefcase icon). The frontend routes to the Capstone screen and the breadcrumb
   reads `App / Capstone Agent`.

## Submit a Request

1. (Optional) Upload one or more documents (each ≤ 10 MB) to ingest them into the
   knowledge base for retrieval; the screen confirms each successfully ingested
   document.
2. Type your task into the agent prompt box, describing the multi-tool query you
   want the Agent to complete.
3. Click **Synthesize Multi-Tool Task** to send the task to the Capstone
   Backend_Service. A task with no non-whitespace characters is rejected with a
   validation message and the Agent is not started.

## View the Response

1. While the Agent plans and executes, a step feed streams over SSE and updates per
   step, identifying the phase (planning, tool invocation, retrieval, or answer
   synthesis) and its sequence position.
2. When the run completes, the final answer is shown together with the list of MCP
   tools the Agent invoked (with any failed tool flagged) and the source documents
   it referenced.
3. If the Agent reaches the 25-step limit without a final answer, the results
   gathered so far are shown with an indication that the step limit was reached.
4. Use the **History** toggle in the top bar to browse previously persisted task
   runs and ingestions and reopen earlier results.
