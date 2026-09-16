#!/usr/bin/env bash
# Exercise auth-service's native endpoints against the dev stack.
#
# The successor to `scripts/dev/keycloak-test.sh` for everything that is
# moving off Keycloak. Both exist during the cut-over so the two can be
# compared side by side; the Keycloak one is deleted in IDX-B2.
#
#   ./scripts/dev/auth-test.sh s2s      # client_credentials (IDX-B1b)
#   ./scripts/dev/auth-test.sh jwks     # discovery + signing keys
set -euo pipefail

AUTH_URL="${AUTH_URL:-http://localhost:8000}"
DEV_DEVICE_ID="${DEV_DEVICE_ID:-0000000d-0000-0000-0000-00000000d0e1}"
DEV_DEVICE_SECRET="${DEV_DEVICE_SECRET:-dev-room-device-secret}"

die() { printf '\033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }
ok()  { printf '\033[32m  ok\033[0m %s\n' "$1"; }

cmd_s2s() {
  echo "== client_credentials against ${AUTH_URL} =="

  local body status token
  body="$(curl -sS -w '\n%{http_code}' -X POST "${AUTH_URL}/auth/oauth/token" \
      -d grant_type=client_credentials \
      -d "client_id=${DEV_DEVICE_ID}" \
      -d "client_secret=${DEV_DEVICE_SECRET}")"
  status="$(tail -n1 <<<"$body")"
  # `sed '$d'` drops the trailing status line. NOT `head -n-1`, which is a
  # GNU extension and fails on the BSD head that ships with macOS — where
  # half of this team runs the dev stack.
  body="$(sed '$d' <<<"$body")"
  [ "$status" = "200" ] || die "grant returned ${status}: ${body}"
  token="$(jq -r .access_token <<<"$body")"
  [ -n "$token" ] && [ "$token" != "null" ] || die "no access_token in the response"
  ok "device got a token"

  # Decode the payload without verifying — this is a smoke test, and the
  # signature is what the contract test covers. base64url needs its
  # padding restored by hand; macOS `base64 -d` rejects the unpadded form
  # that JWTs use.
  local claims payload pad
  payload="$(cut -d. -f2 <<<"$token" | tr '_-' '/+')"
  pad=$(( (4 - ${#payload} % 4) % 4 ))
  payload="${payload}$(printf '=%.0s' $(seq 0 $((pad - 1)) 2>/dev/null))"
  claims="$(base64 -d <<<"$payload" 2>/dev/null || base64 --decode <<<"$payload")"
  jq -e '.roles == ["device"]' >/dev/null <<<"$claims" || die "roles is not [device]"
  ok "roles = [device]"
  jq -e '.tid != null' >/dev/null <<<"$claims" || die "no tid claim"
  ok "tid = $(jq -r .tid <<<"$claims")"
  jq -e '.aud == "mdx-api"' >/dev/null <<<"$claims" || die "aud is not mdx-api"
  ok "aud = mdx-api"

  # No refresh token, ever: a machine holding its own secret can ask again.
  jq -e 'has("refresh_token") | not' >/dev/null <<<"$body" \
    || die "the response carried a refresh token"
  ok "no refresh token"

  status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${AUTH_URL}/auth/oauth/token" \
      -d grant_type=client_credentials \
      -d "client_id=${DEV_DEVICE_ID}" \
      -d "client_secret=definitely-not-the-secret")"
  [ "$status" = "401" ] || die "a wrong secret returned ${status}, expected 401"
  ok "a wrong secret is 401 invalid_client"

  echo "== s2s OK =="
}

cmd_jwks() {
  echo "== discovery + JWKS against ${AUTH_URL} =="
  curl -sS "${AUTH_URL}/.well-known/openid-configuration" | jq -e .issuer >/dev/null \
    || die "no discovery document"
  ok "discovery document served"
  curl -sS "${AUTH_URL}/.well-known/jwks.json" | jq -e '.keys | length > 0' >/dev/null \
    || die "JWKS is empty"
  ok "JWKS has at least one key"
  echo "== jwks OK =="
}

case "${1:-}" in
  s2s)  cmd_s2s ;;
  jwks) cmd_jwks ;;
  *)    echo "usage: $0 {s2s|jwks}" >&2; exit 2 ;;
esac
