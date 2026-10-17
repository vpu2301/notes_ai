#!/usr/bin/env bash
# workspace-smoke.sh — W1: sign in with an e-mail code, switch workspace, refresh, borrow,
# log out; once per client transport (web = cookie, macos/ios = body). Exits non-zero on
# the first mismatch and prints the count of wrong-workspace answers.
#
#   scripts/dev/workspace-smoke.sh                      # member@tenant-a.example
#   SMOKE_EMAIL=me@x.test scripts/dev/workspace-smoke.sh
#
# Needs: the stack up in MDX_IDP_MODE=dual|native, mail going to Mailpit (the sign-in
# code is read from the mailbox — never point this at a real relay), and an account
# that holds a Personal workspace plus at least one team workspace
# (`python -m auth_service.ops.ensure_personal` heals a missing Personal one).
set -euo pipefail
cd "$(dirname "$0")/../.."

AUTH_URL="${AUTH_URL:-http://localhost:8000}"
MAILPIT_URL="${MAILPIT_URL:-http://localhost:8025}"
SMOKE_EMAIL="${SMOKE_EMAIL:-member@tenant-a.example}"
TRANSPORTS="${TRANSPORTS:-web macos ios}"

WRONG=0
JAR="$(mktemp)"
OUT="$(mktemp)"
trap 'rm -f "$JAR" "$OUT"' EXIT

fail() {
  printf '\033[31m✗ %s\033[0m\n' "$*" >&2
  printf 'wrong-workspace answers: %s\n' "$WRONG" >&2
  exit 1
}
ok() { printf '\033[32m✓ %s\033[0m\n' "$*"; }

# req METHOD PATH CLIENT [BEARER] [JSON] → response body in $BODY, HTTP code in $CODE.
# Globals, not stdout: a $(…) subshell would lose $CODE.
req() {
  local method=$1 path=$2 client=$3 bearer=${4:-} body=${5:-}
  local args=(-s -o "$OUT" -w '%{http_code}' -X "$method" "$AUTH_URL$path"
    -H "X-Client-Type: $client" -H 'Content-Type: application/json')
  [[ -n "$bearer" ]] && args+=(-H "Authorization: Bearer $bearer")
  [[ -n "$body" ]] && args+=(--data "$body")
  [[ "$client" == web ]] && args+=(-b "$JAR" -c "$JAR")
  CODE=$(curl "${args[@]}")
  BODY=$(cat "$OUT")
}

last_code() {
  uv run python scripts/ci/mailpit-last-code.py "$SMOKE_EMAIL" --base "$MAILPIT_URL" --wait "$1" 2>/dev/null
}

sign_in() {
  local client=$1 start previous
  # The mailbox keeps the previous transport's code; wait for a different one.
  previous=$(last_code 0 || true)
  req POST /auth/email/start "$client" "" "{\"email\":\"$SMOKE_EMAIL\"}"; start=$BODY
  if [[ "$CODE" == 429 ]]; then
    # One code per address per cooldown; the previous transport just asked for one.
    local wait_s
    wait_s=$(jq -r '.retry_after // 60' <<<"$start" 2>/dev/null || echo 60)
    echo "  (resend cooldown: waiting ${wait_s}s)"
    sleep "$wait_s"
    req POST /auth/email/start "$client" "" "{\"email\":\"$SMOKE_EMAIL\"}"; start=$BODY
  fi
  [[ "$CODE" == 202 ]] || fail "$client: /auth/email/start → $CODE $start"
  local challenge code
  challenge=$(jq -r .challenge_id <<<"$start")
  local tries=0
  code=""
  while [[ -z "$code" || "$code" == "$previous" ]]; do
    tries=$((tries + 1))
    ((tries <= 20)) || fail "$client: no new sign-in code in Mailpit for $SMOKE_EMAIL (is mail going to Mailpit?)"
    code=$(last_code 1 || true)
  done
  req POST /auth/email/verify "$client" "" "{\"challenge_id\":\"$challenge\",\"code\":\"$code\"}"; VERIFY=$BODY
  [[ "$CODE" == 200 ]] || fail "$client: /auth/email/verify → $CODE $VERIFY"
  [[ "$(jq -r .status <<<"$VERIFY")" == authenticated ]] || fail "$client: MFA owed — use an account without it"
}

refresh() {
  local client=$1
  if [[ "$client" == web ]]; then
    req POST /auth/refresh "$client"
  else
    req POST /auth/refresh "$client" "" "{\"refresh_token\":\"$REFRESH\"}"
  fi
}

run_transport() {
  local client=$1
  echo "── $client ──────────────────────────────────────────────"
  sign_in "$client"
  local access team personal me tenants out tid
  access=$(jq -r .access_token <<<"$VERIFY")
  REFRESH=$(jq -r '.refresh_token // empty' <<<"$VERIFY")
  if [[ "$client" == web ]]; then
    [[ -z "$REFRESH" ]] || fail "web: refresh token leaked into the body"
  else
    [[ -n "$REFRESH" ]] || fail "$client: no refresh token in the body"
  fi
  ok "$client: signed in with an e-mail code"

  req GET /auth/me "$client" "$access"; me=$BODY
  [[ "$CODE" == 200 ]] || fail "$client: /auth/me → $CODE"
  personal=$(jq -r '.personal_tenant_id // empty' <<<"$me")
  [[ -n "$personal" ]] || fail "$client: no Personal workspace (run auth_service.ops.ensure_personal)"
  [[ "$(jq -r '.db_user != null and .active_membership != null' <<<"$me")" == true ]] \
    || fail "$client: /auth/me has no db_user/active_membership"
  ok "$client: /auth/me describes the active membership"

  req GET /tenants "$client" "$access"; tenants=$BODY
  [[ "$CODE" == 200 ]] || fail "$client: /tenants → $CODE"
  team=$(jq -r '[.items[] | select(.kind == "team")][0].id // empty' <<<"$tenants")
  [[ -n "$team" ]] || fail "$client: $SMOKE_EMAIL belongs to no team workspace"
  [[ "$(jq -r '.items[0].kind' <<<"$tenants")" == personal ]] || fail "$client: Personal is not listed first"
  ok "$client: /tenants lists Personal first and a team workspace"

  req POST /auth/token "$client" "$access" "{\"tenant_id\":\"$team\"}"; out=$BODY
  [[ "$CODE" == 200 ]] || fail "$client: switch → $CODE $out"
  access=$(jq -r .access_token <<<"$out")
  req GET /tenants/current "$client" "$access"; tid=$(jq -r .id <<<"$BODY")
  [[ "$tid" == "$team" ]] || { WRONG=$((WRONG + 1)); fail "$client: /tenants/current is $tid, not $team"; }
  ok "$client: switched to the team workspace"

  refresh "$client"; out=$BODY
  [[ "$CODE" == 200 ]] || fail "$client: refresh → $CODE $out"
  [[ "$(jq -r .tenant_id <<<"$out")" == "$team" ]] || { WRONG=$((WRONG + 1)); fail "$client: refresh left the team workspace"; }
  access=$(jq -r .access_token <<<"$out")
  [[ "$client" == web ]] || REFRESH=$(jq -r .refresh_token <<<"$out")
  req GET /auth/me "$client" "$access"; tid=$(jq -r .claims.tid <<<"$BODY")
  [[ "$tid" == "$team" ]] || { WRONG=$((WRONG + 1)); fail "$client: after refresh tid is $tid"; }
  ok "$client: refresh confirms the team workspace"

  req POST /auth/token "$client" "$access" "{\"tenant_id\":\"$personal\",\"activate\":false}"; out=$BODY
  [[ "$CODE" == 200 && "$(jq -r .tenant_id <<<"$out")" == "$personal" ]] || fail "$client: borrow → $CODE $out"
  refresh "$client"; out=$BODY
  [[ "$(jq -r .tenant_id <<<"$out")" == "$team" ]] || { WRONG=$((WRONG + 1)); fail "$client: a borrowed token moved the session"; }
  access=$(jq -r .access_token <<<"$out")
  [[ "$client" == web ]] || REFRESH=$(jq -r .refresh_token <<<"$out")
  ok "$client: a borrowed Personal token leaves the session in the team workspace"

  # Back to Personal so the next run starts from the same place.
  req POST /auth/token "$client" "$access" "{\"tenant_id\":\"$personal\"}"
  if [[ "$client" == web ]]; then
    req POST /auth/logout "$client" "$access"
  else
    req POST /auth/logout "$client" "$access" "{\"refresh_token\":\"$REFRESH\"}"
  fi
  [[ "$CODE" == 204 ]] || fail "$client: logout → $CODE"
  refresh "$client"
  [[ "$CODE" == 401 ]] || fail "$client: refresh after logout → $CODE (want 401)"
  ok "$client: logout revokes the session"
}

for t in $TRANSPORTS; do
  : >"$JAR"
  run_transport "$t"
done
printf 'wrong-workspace answers: %s\n' "$WRONG"
