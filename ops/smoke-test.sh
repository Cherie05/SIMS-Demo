#!/bin/sh
# Post-deployment checks. SMOKE_INSECURE=1 accepts a local CA; SMOKE_HTTP_URL overrides the redirect URL.
# Check invokes probe functions through its argument list.
# shellcheck disable=SC2329
set -u
BASE=${1:?usage: smoke-test.sh <public url>}
BASE=${BASE%/}
case "$BASE" in http://*|https://*) ;; *) echo "A HTTP(S) public URL is required" >&2; exit 2 ;; esac
failures=0

curl_request() {
  if [ "${SMOKE_INSECURE:-0}" = 1 ]; then
    curl -sS --max-time 10 --connect-timeout 5 --insecure "$@"
  else
    curl -sS --max-time 10 --connect-timeout 5 "$@"
  fi
}
check() {
  name=$1
  shift
  if "$@" > /dev/null 2>&1; then
    printf 'ok    %s\n' "$name"
  else
    printf 'FAIL  %s\n' "$name"
    failures=$((failures + 1))
  fi
}
status_is() { [ "$(curl_request -o /dev/null -w '%{http_code}' "$1")" = "$2" ]; }
has_header() {
  headers=$(curl_request -I "$1") || return 1
  printf '%s\n' "$headers" | grep -qi "^$2:"
}
api_answers() {
  body=$(curl_request -f "$BASE/api/v1/auth/config") || return 1
  printf '%s\n' "$body" | grep -q '"signup_enabled"'
}
codes_use_email() {
  body=$(curl_request -f "$BASE/api/v1/auth/config") || return 1
  printf '%s\n' "$body" | grep -Eq '"otp_delivery"[[:space:]]*:[[:space:]]*"email"'
}
docs_disabled() { status_is "$BASE/api/openapi.json" 404 && status_is "$BASE/api/docs" 404; }
http_redirects() {
  case "$(curl_request -o /dev/null -w '%{http_code}' "$HTTP_URL/")" in
    301|302|307|308)
      headers=$(curl_request -I "$HTTP_URL/") || return 1
      printf '%s\n' "$headers" | grep -qi '^location: https://'
      ;;
    *) return 1 ;;
  esac
}

# Retry the first probe while containers finish starting
i=0
until curl_request -o /dev/null -f "$BASE/api/v1/auth/config" 2>/dev/null || [ "$i" -ge 20 ]; do i=$((i + 1)); sleep 3; done

check "web app loads" curl_request -f -o /dev/null "$BASE/"
check "API answers" api_answers
check "API refuses anonymous access" status_is "$BASE/api/v1/orders" 401
check "security headers" has_header "$BASE/" content-security-policy
check "request ids" has_header "$BASE/api/v1/auth/config" x-request-id
check "no API docs in production" docs_disabled
check "one-time codes use email" codes_use_email
case "$BASE" in
  https://*)
    check "HSTS" has_header "$BASE/" strict-transport-security
    # plain HTTP on port 80 by default; SMOKE_HTTP_URL when it is published elsewhere
    HTTP_URL=${SMOKE_HTTP_URL:-$(printf '%s' "$BASE" | sed 's#^https://#http://#; s#:[0-9]*$##')}
    check "HTTP redirects to HTTPS" http_redirects
    ;;
esac

[ "$failures" -eq 0 ] && echo "Smoke test passed" || echo "Smoke test failed ($failures)"
exit "$failures"
