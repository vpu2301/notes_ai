#!/usr/bin/env bash
# IDX-B3 G — load proof for the native auth hot paths.
#
#   ./scripts/loadtest/run-auth-loadtest.sh [smoke|main|locked] [outdir]
#
# Requires a NATIVE-mode auth-service (MDX_IDP_MODE=native) with the dev
# signing key, the mock mail provider, Postgres and Redis. The wrapper
# does not start one — pointing a load test at whatever happens to be on
# :8000 is how you measure the wrong build.
#
# k6 runs from the grafana/k6 image; host.docker.internal reaches the
# local service. Thresholds are enforced inside k6, so a red run exits
# non-zero here too.
set -euo pipefail

cd "$(dirname "$0")/../.."
SCENARIO="${1:-smoke}"
OUT="${2:-docs/perf}"
mkdir -p "$OUT"

K6_IMAGE=grafana/k6:0.57.0
AUTH_URL="${AUTH_URL:-http://localhost:8000}"
IN_DOCKER_URL="${IN_DOCKER_URL:-http://host.docker.internal:8000}"
PROM="${PROM:-http://localhost:9090}"
STAMP="$(date +%Y-%m-%d)"
REPORT="$OUT/idx-auth-loadtest-$STAMP.md"

log() { printf '\n== %s ==\n' "$*"; }
die() { printf '\033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }

log "preflight"
curl -sf "$AUTH_URL/healthz" >/dev/null || die "auth-service is not up on $AUTH_URL"
# The native routes only exist in native mode; without this the run would
# measure a wall of 404s and report them as fast.
curl -sf "$AUTH_URL/.well-known/jwks.json" >/dev/null \
  || die "no JWKS — auth-service is not in MDX_IDP_MODE=native"
echo "  ok: native auth-service on $AUTH_URL"

log "k6 ($SCENARIO)"
SUMMARY="$(mktemp)"
docker run --rm -i \
  --add-host=host.docker.internal:host-gateway \
  -e "SCENARIO=$SCENARIO" \
  -e "BASE_URL=$IN_DOCKER_URL" \
  -e "DEVICE_ID=${DEVICE_ID:-0000000d-0000-0000-0000-00000000d0e1}" \
  -e "DEVICE_SECRET=${DEVICE_SECRET:-dev-room-device-secret}" \
  "$K6_IMAGE" run --summary-export=/dev/stderr - \
  < scripts/loadtest/auth-k6.js 2>"$SUMMARY" || K6_FAILED=1

prom() {
  curl -s "$PROM/api/v1/query" --data-urlencode "query=$1" 2>/dev/null |
    python3 -c 'import sys,json
try:
    r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "n/a")
except Exception: print("n/a")'
}

log "writing $REPORT"
{
  echo "# IDX auth load test — $STAMP"
  echo
  echo "Scenario: \`$SCENARIO\` · target: \`$AUTH_URL\` · image: \`$K6_IMAGE\`"
  echo
  echo "## What was measured"
  echo
  echo "The pack's target table names \`/auth/refresh\`, \`/auth/token\` and"
  echo "Argon2 \`/auth/login\`. None exist yet — the native session routes are"
  echo "IDX-A2's undelivered half and passwords are IDX-A4. Measuring the"
  echo "Keycloak-backed login instead would produce a number describing"
  echo "software that is being deleted. These are the native hot paths that"
  echo "do exist:"
  echo
  echo '| Endpoint | p95 observed | Threshold | Note |'
  echo '| --- | --- | --- | --- |'
  python3 - "$SUMMARY" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print('| _(k6 summary unavailable)_ | | | |'); raise SystemExit
rows = [
    ("/auth/email/start", "idx_email_start_ms", 400, "Redis + DB + inline mail (mock provider)"),
    ("/auth/email/verify", "idx_email_verify_ms", 300, "hash compare + attempt bookkeeping"),
    ("/auth/oauth/token", "idx_oauth_token_ms", 150, "secret hash lookup + RS256 sign"),
    ("/.well-known/jwks.json", "idx_jwks_ms", 50, "served in process in native mode"),
]
for label, metric, budget, note in rows:
    m = d.get("metrics", {}).get(metric, {})
    p95 = m.get("p(95)")
    print(f'| `{label}` | {p95:.1f} ms | < {budget} ms | {note} |' if p95 is not None
          else f'| `{label}` | not exercised | < {budget} ms | {note} |')
reqs = d.get("metrics", {}).get("http_reqs", {})
failed = d.get("metrics", {}).get("http_req_failed", {})
print()
print(f'Requests: {reqs.get("count", "n/a")} · failure rate: {failed.get("value", "n/a")}')
PY
  echo
  echo "## System under load"
  echo
  echo '| Signal | Value |'
  echo '| --- | --- |'
  echo "| DB connections (auth pools) | $(prom 'sum(pg_stat_activity_count{datname="notes"})') |"
  echo "| Sign-in codes sent | $(prom 'sum(increase(mdx_auth_otp_start_total{result="sent"}[10m]))') |"
  echo "| Sign-in codes rate limited | $(prom 'sum(increase(mdx_auth_otp_start_total{result="rate_limited"}[10m]))') |"
  echo "| Device grants ok | $(prom 'sum(increase(mdx_auth_client_credentials_total{result="ok"}[10m]))') |"
  echo "| Device grants locked | $(prom 'sum(increase(mdx_auth_client_credentials_total{result="locked"}[10m]))') |"
  echo "| Inline mail p95 (s) | $(prom 'histogram_quantile(0.95, sum by (le) (rate(mdx_auth_email_send_seconds_bucket[10m])))') |"
  echo
  echo "## Notes"
  echo
  echo "- A 429 on \`/auth/email/start\` is a **correct** answer under load:"
  echo "  the whole test drives from one address, so the per-IP cap engages."
  echo "  It is counted as a pass, not a failure."
  echo "- \`AUTH_ARGON2_*\` tuning is deferred to IDX-A4, which introduces the"
  echo "  password hash this sprint has nothing to measure."
} > "$REPORT"

cat "$REPORT"
[ -z "${K6_FAILED:-}" ] || die "k6 thresholds were not met (report written anyway)"
log "OK — $REPORT"
