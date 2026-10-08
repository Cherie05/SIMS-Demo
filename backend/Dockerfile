# syntax=docker/dockerfile:1
# One image, three roles (see docker-entrypoint.sh): API (default), "worker", and "migrate".
ARG PYTHON_IMAGE=python:3.11.17-slim-trixie

# ---------------------------------------------------------------- build: dependencies into a venv
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
# Every package is pinned and verified against the SHA-256 hashes in the lockfile (supply chain).
# The packaging tools venv brings along (pip, setuptools with its vendored wheel) aren't needed at
# runtime and only add attack surface, so they're removed once the dependencies are in.
RUN pip install --require-hashes --no-deps -r requirements.txt \
    && pip uninstall -y setuptools \
    && pip uninstall -y pip

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ARG APP_VERSION=1.1.0
LABEL org.opencontainers.image.title="sims-backend" \
      org.opencontainers.image.description="Sales & Inventory Management System - API, worker and migrations" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="Proprietary"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    APP_VERSION=${APP_VERSION}

# pip/setuptools aren't needed at runtime: removing them shrinks the attack surface and scanner noise.
RUN python -m pip uninstall -y pip setuptools wheel >/dev/null 2>&1 || true \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# Code is owned by root and only readable by the app user; containers also run with a read-only root FS.
COPY . .
RUN chmod 0755 docker-entrypoint.sh && python -m compileall -q app scripts alembic

USER app
EXPOSE 8000 9101
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
# --proxy-headers: trust X-Forwarded-For from the proxy in front (only the proxies can reach this port).
# uvicorn drains in-flight requests for up to 20 s on SIGTERM; the app's own access log replaces uvicorn's.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log", "--timeout-graceful-shutdown", "20", "--timeout-keep-alive", "5"]
