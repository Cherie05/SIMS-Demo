# syntax=docker/dockerfile:1
# ---------------------------------------------------------------- build
FROM node:22.23.3-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Exact versions from the lockfile; no install scripts from dependencies.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build

# ---------------------------------------------------------------- serve: static files + reverse proxy for /api
# Unprivileged image: runs as uid 101 on port 8080, so the container needs no capabilities at all.
FROM nginxinc/nginx-unprivileged:1.31.5-alpine
ARG APP_VERSION=1.1.0
LABEL org.opencontainers.image.title="sims-frontend" \
      org.opencontainers.image.description="Sales & Inventory Management System - web app and API proxy" \
      org.opencontainers.image.version="${APP_VERSION}"
# Security updates for the OS packages of the base image, then back to the unprivileged user.
USER root
RUN apk upgrade --no-cache
USER 101
ENV NGINX_BACKEND=backend:8000     NGINX_RESOLVER=127.0.0.11 \
    NGINX_TRUSTED_PROXY=127.0.0.1 \
    NGINX_ENVSUBST_FILTER=^NGINX_
# The entrypoint renders templates into /etc/nginx/conf.d (a tmpfs when the root FS is read-only).
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY security-headers.conf api-proxy.conf /etc/nginx/snippets/
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
