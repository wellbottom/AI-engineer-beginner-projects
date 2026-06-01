# Shared_Frontend (Vite + React SPA) — Requirement 11.2.
#
# ───────────────────────────────────────────────────────────────────────────
# BUILD-CONTEXT CAVEAT (tracked: development/buglists.md BUG-011)
# ───────────────────────────────────────────────────────────────────────────
# The frontend currently lives at ./ai-monorepo-frontend (repo root). Task 16
# RELOCATES it to ./apps/web. While it lives here, docker-compose.yml points the
# `web` service build context at `./ai-monorepo-frontend`. When Task 16 moves the
# SPA, the Compose `web.build.context` MUST change to `./apps/web` (this
# Dockerfile and nginx.conf move with the frontend; their relative COPY paths are
# unchanged). See the CLEAR COMMENT in docker-compose.yml.
#
# Multi-stage: (1) build the static Vite bundle, (2) serve it with nginx.
#
# Backend base URLs are BUILD-TIME args (Vite inlines VITE_* into the bundle at
# build time — Requirement 2.9). They are declared as the six VITE_* names the
# design fixes (VITE_PLAYGROUND_URL, ...), passed by docker-compose.yml from the
# root .env. Because the pre-Task-16 SPA code (src/lib/api.ts) still reads the
# NEXT_PUBLIC_* / VITE_NEXT_PUBLIC_* names, this stage ALSO forwards each VITE_*
# value to its VITE_NEXT_PUBLIC_* alias so the current bundle picks them up. Task
# 16.2 renames the SPA to read VITE_* directly, after which the alias lines below
# can be dropped.

# ── Stage 1: build the static bundle ───────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# The six backend base URLs (build-time). Empty defaults keep the build working
# even if a URL is not supplied (the SPA degrades gracefully).
ARG VITE_PLAYGROUND_URL=""
ARG VITE_SUPPORT_URL=""
ARG VITE_WEBAGENT_URL=""
ARG VITE_DEEPRESEARCH_URL=""
ARG VITE_IMAGE_URL=""
ARG VITE_CAPSTONE_URL=""

# Expose the VITE_* names to `vite build` (Task 16 target names, Requirement 2.9)
# AND the VITE_NEXT_PUBLIC_* aliases the current SPA code reads (bridge until
# Task 16.2 renames the env). Both point at the same supplied values.
ENV VITE_PLAYGROUND_URL=$VITE_PLAYGROUND_URL \
    VITE_SUPPORT_URL=$VITE_SUPPORT_URL \
    VITE_WEBAGENT_URL=$VITE_WEBAGENT_URL \
    VITE_DEEPRESEARCH_URL=$VITE_DEEPRESEARCH_URL \
    VITE_IMAGE_URL=$VITE_IMAGE_URL \
    VITE_CAPSTONE_URL=$VITE_CAPSTONE_URL \
    VITE_NEXT_PUBLIC_PLAYGROUND_URL=$VITE_PLAYGROUND_URL \
    VITE_NEXT_PUBLIC_SUPPORT_URL=$VITE_SUPPORT_URL \
    VITE_NEXT_PUBLIC_WEBAGENT_URL=$VITE_WEBAGENT_URL \
    VITE_NEXT_PUBLIC_DEEPRESEARCH_URL=$VITE_DEEPRESEARCH_URL \
    VITE_NEXT_PUBLIC_IMAGE_URL=$VITE_IMAGE_URL \
    VITE_NEXT_PUBLIC_CAPSTONE_URL=$VITE_CAPSTONE_URL

# Install dependencies from the lockfile (deterministic). The frontend is still a
# standalone npm package here; Task 16 folds it into the pnpm workspace.
COPY package.json package-lock.json ./
RUN npm ci

# Build the static bundle (vite build -> /app/dist).
COPY . .
RUN npm run build

# ── Stage 2: serve the static bundle ────────────────────────────────────────
FROM nginx:1.27-alpine AS serve

# SPA-aware nginx config (client-side routing fallback to /index.html).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# The built bundle.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine ships a default CMD that runs nginx in the foreground.
