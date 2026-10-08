#!/bin/sh
# Roles of the backend image:
#   (default)  the API: uvicorn (CMD)
#   migrate    apply database migrations once, then exit (run as a release step, before the API starts)
#   worker     the background worker (emails, retries, scheduled housekeeping)
set -e

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  case "${ENVIRONMENT:-development}" in
    production|staging) echo "Demo data is forbidden in staging/production" >&2; exit 1 ;;
  esac
fi

case "${1:-}" in
  migrate)
    echo "Applying database migrations..."
    alembic upgrade head
    # Demo data (users with published passwords) is for local review only.
    if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
      echo "Loading demo data (skipped if data already exists)..."
      python -m scripts.seed
    fi
    exit 0
    ;;
  worker)
    exec python -m app.worker
    ;;
esac

# Single-container setups can still migrate on start; with several API replicas use the migrate role.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  alembic upgrade head
fi

exec "$@"
