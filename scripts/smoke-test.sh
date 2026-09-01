#!/usr/bin/env bash
# smoke-test.sh — verify the local stack is reachable.
# Usage: git clone && make dev-up && make smoke-test
set -euo pipefail

AUTH_URL="${AUTH_URL:-http://localhost:8000}"
ASR_URL="${ASR_URL:-http://localhost:8001}"
DICTATION_URL="${DICTATION_URL:-http://localhost:8002}"
NOTIFICATION_URL="${NOTIFICATION_URL:-http://localhost:8004}"
NLP_URL="${NLP_URL:-http://localhost:8005}"
NOTE_URL="${NOTE_URL:-http://localhost:8006}"
AUTOCOMPLETE_URL="${AUTOCOMPLETE_URL:-http://localhost:8007}"
GENERATION_URL="${GENERATION_URL:-http://localhost:8009}"

JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
LOKI_URL="${LOKI_URL:-http://localhost:3100}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"

PASS=0
FAIL=0

check() {
  local name=$1 url=$2 expected=${3:-}
  local body
  if body=$(curl -sf --max-time 5 "$url"); then
    if [[ -n "$expected" && "$body" != *"$expected"* ]]; then
      printf '\033[31m✗ %s — response did not contain "%s"\033[0m\n' "$name" "$expected"
      FAIL=$((FAIL + 1))
    else
      printf '\033[32m✓ %s\033[0m\n' "$name"
      PASS=$((PASS + 1))
    fi
  else
    printf '\033[31m✗ %s — unreachable at %s\033[0m\n' "$name" "$url"
    FAIL=$((FAIL + 1))
  fi
}

echo "==================================================================="
echo " Smoke Tests — Notes AI Backend"
echo "==================================================================="
echo ""

echo "── Infrastructure ─────────────────────────────────────────────────"
check "Jaeger UI"         "$JAEGER_URL/api/services"             ""
check "Prometheus"        "$PROMETHEUS_URL/-/healthy"            "Prometheus Server is Healthy"
check "Grafana"           "$GRAFANA_URL/api/health"              "ok"
check "Loki ready"        "$LOKI_URL/ready"                      "ready"

echo ""
echo "── Application services (asr-worker is a queue consumer — no HTTP) ─"
check "auth-service         /healthz" "$AUTH_URL/healthz"         '"status":"ok"'
check "asr-service          /healthz" "$ASR_URL/healthz"          '"status":"ok"'
check "dictation-service    /healthz" "$DICTATION_URL/healthz"    '"status":"ok"'
check "notification-service /healthz" "$NOTIFICATION_URL/healthz" '"status":"ok"'
check "nlp-service          /healthz" "$NLP_URL/healthz"          '"status":"ok"'
check "note-service         /healthz" "$NOTE_URL/healthz"         '"status":"ok"'
check "autocomplete-service /healthz" "$AUTOCOMPLETE_URL/healthz" '"status":"ok"'
check "generation-service   /healthz" "$GENERATION_URL/healthz"   '"status":"ok"'

echo ""
echo "─────────────────────────────────────────────────────────────────────"
printf "Results: \033[32m%d passed\033[0m, \033[31m%d failed\033[0m\n" "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
