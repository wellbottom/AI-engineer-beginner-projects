# Ask the Web Agent — User Guide

Step-by-step instructions for operating Ask the Web through the Shared_Frontend.

## Navigate to Project

1. Start the Shared_Frontend (`apps/web`) and the Web Agent Backend_Service
   (port **8003**), and open the frontend in your browser.
2. In the left sidebar, under **Projects Sandbox**, select **Ask the Web** (the
   globe icon). The frontend routes to the answer screen and the breadcrumb reads
   `App / Ask the Web`.

## Submit a Request

1. Type your question into the search bar (1–2,000 characters).
2. Click **Retrieve Web Solution** (or press Enter) to send the question to the Web
   Agent Backend_Service. An empty, whitespace-only, or over-length question is
   rejected with a validation message and no search is performed.

## View the Response

1. While the agent searches and synthesizes, a loading indicator is shown and the
   answer then streams into the result area incrementally.
2. When the answer completes, the cited source URLs (drawn from the retrieved web
   results) are listed alongside it.
3. If no relevant web sources are found, a "no relevant web sources found" message
   is shown with no citations.
4. If the search fails or times out (30s), a human-readable error identifying the
   search failure is shown with no citations, and your input is retained.
5. Use the **History** toggle in the top bar to browse previously persisted asks
   and reopen earlier answers.
