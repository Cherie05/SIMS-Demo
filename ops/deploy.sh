#!/bin/sh
# Deploy digest-pinned release images. Migrations must be backward compatible with the previous release.
#   sh ops/deploy.sh v1.2.3 <backend image@digest> <frontend image@digest>
#   sh ops/deploy.sh --rollback
set -eu
umask 077

cd "$(dirname "$0")/.."
STATE_DIR=${STATE_DIR:-/var/lib/sims-deploy}
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
if ! mkdir "$STATE_DIR/lock" 2>/dev/null; then
  echo "Another deployment holds $STATE_DIR/lock; inspect it before retrying." >&2
  exit 1
fi
trap 'rmdir "$STATE_DIR/lock"; rm -f "$STATE_DIR/current.tmp"' 0

compose() { docker compose --env-file production.env -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
log() { printf '{"event":"deploy.%s","release":"%s","time":"%s"}\n' "$1" "$RELEASE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; }
validate_release() {
  printf '%s\n' "$RELEASE" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$' || {
    echo "Release must be a version tag (v1.2.3)." >&2; return 1;
  }
  for image in "$BACKEND_IMAGE" "$FRONTEND_IMAGE"; do
    printf '%s\n' "$image" | grep -Eq '^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$' || {
      echo "Both images must be pinned to a SHA-256 digest." >&2; return 1;
    }
  done
}
load_state() {
  RELEASE=''
  BACKEND_IMAGE=''
  FRONTEND_IMAGE=''
  while IFS='=' read -r key value; do
    case "$key" in
      RELEASE) RELEASE=$value ;;
      BACKEND_IMAGE) BACKEND_IMAGE=$value ;;
      FRONTEND_IMAGE) FRONTEND_IMAGE=$value ;;
      *) echo "Invalid deployment state record" >&2; return 1 ;;
    esac
  done < "$1"
  validate_release
}
deploy_release() {
  validate_release || return 1
  export BACKEND_IMAGE FRONTEND_IMAGE
  export APP_VERSION="$RELEASE"
  git checkout --quiet --detach "$RELEASE" || return 1
  compose config --quiet || return 1
  compose pull backend worker migrate frontend || return 1
  compose up -d --no-build --wait --wait-timeout 300 mysql redis || return 1
  # Compose may reuse a completed one-shot container; always run the release steps.
  compose run --rm --no-deps db-init || return 1
  # A rollback retains the upgraded schema; older migration scripts cannot resolve a newer revision.
  if [ "${1:-0}" = 0 ]; then compose run --rm --no-deps migrate || return 1; fi
  compose up -d --no-build --no-deps --wait --wait-timeout 300 backend worker frontend edge backup || return 1
  sh ops/smoke-test.sh "${PUBLIC_URL:?PUBLIC_URL must be set in the deployment environment}" || return 1
}

ROLLBACK_MODE=0
if [ "${1:-}" = "--rollback" ]; then
  ROLLBACK_MODE=1
  [ -f "$STATE_DIR/previous" ] || { echo "No previous release recorded" >&2; exit 1; }
  load_state "$STATE_DIR/previous"
else
  RELEASE=${1:?release tag}
  BACKEND_IMAGE=${2:?backend image}
  FRONTEND_IMAGE=${3:?frontend image}
fi
validate_release
git fetch --tags --quiet || exit 1
log started
if deploy_release "$ROLLBACK_MODE"; then
  [ ! -f "$STATE_DIR/current" ] || cp "$STATE_DIR/current" "$STATE_DIR/previous"
  printf 'RELEASE=%s\nBACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\n' "$RELEASE" "$BACKEND_IMAGE" "$FRONTEND_IMAGE" > "$STATE_DIR/current.tmp"
  mv "$STATE_DIR/current.tmp" "$STATE_DIR/current"
  log succeeded
  exit 0
fi

log failed
if [ "$ROLLBACK_MODE" = 0 ] && [ -f "$STATE_DIR/current" ]; then
  echo "Release failed: restoring the last successful release." >&2
  load_state "$STATE_DIR/current"
  if deploy_release 1; then log rolled_back; else log rollback_failed; fi
fi
# Restoring the previous version does not make the failed release successful in CI.
exit 1
