# Shared_Frontend (Vite + React SPA) — Requirement 11.2.
#
# The SPA lives at ./apps/web (this is the Docker build context — see
# docker-compose.yml `web.build.context`). This Dockerfile and nginx.conf live
# alongside it, so the COPY paths below are relative to the context.
#
# Multi-stage: (1) build the static Vite bundle, (2) serve it with nginx.
#
# Backend base URLs are BUILD-TIME args (Vite inlines VITE_* into the bundle at
# build time — Requirement 2.9). They are declared as the six VITE_* names the
# design fixes (VITE_PLAYGROUND_URL, ...), passed by docker-compose.yml from the
# root .env. The SPA (src/lib/api.ts) reads these VITE_* names directly via
# import.meta.env, so no NEXT_PUBLIC_* alias bridge is needed.

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

# Expose the six VITE_* names to `vite build` (Requirement 2.9). The SPA reads
# them directly via import.meta.env.
ENV VITE_PLAYGROUND_URL=$VITE_PLAYGROUND_URL \
    VITE_SUPPORT_URL=$VITE_SUPPORT_URL \
    VITE_WEBAGENT_URL=$VITE_WEBAGENT_URL \
    VITE_DEEPRESEARCH_URL=$VITE_DEEPRESEARCH_URL \
    VITE_IMAGE_URL=$VITE_IMAGE_URL \
    VITE_CAPSTONE_URL=$VITE_CAPSTONE_URL

# Install dependencies. apps/web is part of the pnpm workspace and declares
# @repo/ts-config with the `workspace:*` protocol — but the Docker build context
# is JUST apps/web and uses npm, which can't resolve `workspace:*`. That dep only
# backs the JS tailwind.config.ts and the tsconfig `extends` (dev/lint only); the
# Tailwind v4 build is CSS-first (@theme in src/index.css), so `vite build` does
# NOT consume @repo/ts-config. Strip that single workspace-only devDependency
# before installing so the isolated npm build succeeds (tracked: buglists BUG-012).
COPY package.json ./
RUN npm pkg delete "devDependencies.@repo/ts-config" && npm install

# Build the static bundle (vite build -> /app/dist). The JS tailwind.config.ts
# imports @repo/ts-config, which is absent in this isolated context; remove it so
# the CSS-first Tailwind v4 build is unaffected.
COPY . .
RUN rm -f tailwind.config.ts && npm run build

# ── Stage 2: serve the static bundle ────────────────────────────────────────
FROM nginx:1.27-alpine AS serve

# SPA-aware nginx config (client-side routing fallback to /index.html).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# The built bundle.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine ships a default CMD that runs nginx in the foreground.
