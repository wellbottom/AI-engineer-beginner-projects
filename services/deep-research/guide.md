# Deep Research — User Guide

Step-by-step instructions for operating Deep Research through the Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the Deep Research Backend_Service
   (port **8004**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **Deep Research** (the
   search icon). The frontend routes to the research screen and the breadcrumb
   reads `App / Deep Research`.

## Submit a Request

1. Type your research topic into the topic box, describing the analysis context in
   detail.
2. Click **Generate Synthesis Report** to send the topic to the Deep Research
   Backend_Service. An empty or whitespace-only topic is rejected with a validation
   message, and no decomposition or search is performed.

## View the Response

1. As the research runs, a progress feed streams over SSE and updates after each
   step: topic decomposition, a per-sub-question web search, per-sub-question
   embedding storage, and finally report synthesis.
2. When synthesis completes, the full report is displayed with its title,
   introduction, one section per sub-question, and conclusion, with citations on
   each source-drawing section.
3. If a search, embeddings, or synthesis step fails, a human-readable error is
   shown identifying the failure (and, for a search failure, the affected
   sub-question); no partial report is persisted.
4. Use the **History** toggle in the top bar to browse previously persisted reports
   and reopen earlier results.
