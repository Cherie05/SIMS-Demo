#!/bin/sh
# Called by .github/workflows/release.yml: runs ops/deploy.sh on the target host over SSH.
# Host key checking is strict (DEPLOY_KNOWN_HOSTS); the key only exists for the job's lifetime.
set -eu
umask 077

: "${DEPLOY_HOST:?DEPLOY_HOST is required}"
: "${DEPLOY_USER:?DEPLOY_USER is required}"
: "${DEPLOY_SSH_KEY:?DEPLOY_SSH_KEY is required}"
: "${DEPLOY_KNOWN_HOSTS:?DEPLOY_KNOWN_HOSTS is required}"
: "${PUBLIC_URL:?PUBLIC_URL is required}"
# These values enter a remote shell command; restrict them to the documented forms.
printf '%s\n' "$RELEASE" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$' || exit 2
for image in "$BACKEND_IMAGE" "$FRONTEND_IMAGE"; do
  printf '%s\n' "$image" | grep -Eq '^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$' || exit 2
done
printf '%s\n' "$PUBLIC_URL" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$' || {
  echo "PUBLIC_URL must be a HTTPS origin." >&2; exit 2;
}

KEY=$(mktemp)
KNOWN=$(mktemp)
trap 'rm -f "$KEY" "$KNOWN"' EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" > "$KEY"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$KNOWN"

ssh -i "$KEY" -o UserKnownHostsFile="$KNOWN" -o StrictHostKeyChecking=yes -o BatchMode=yes \
  -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -- "$DEPLOY_USER@$DEPLOY_HOST" \
  "cd /opt/sims && PUBLIC_URL='$PUBLIC_URL' sh ops/deploy.sh '$RELEASE' '$BACKEND_IMAGE' '$FRONTEND_IMAGE'"

# Independent check from outside the server's network
sh ops/smoke-test.sh "$PUBLIC_URL"
