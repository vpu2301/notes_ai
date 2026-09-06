#!/usr/bin/env bash
# CI gate (DEP-S1-05): a built image must not carry a token in its config
# (ENV), labels or layer history. Tokens reach the process only from the
# secret manager at runtime.
#   scripts/ci/check-image-no-secrets.sh <image> [<image>…]
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 <image>…" >&2; exit 2; }
pattern='hf_[A-Za-z0-9]{30,}|HF_TOKEN=[^ ]{8,}|HOSTED_MODEL_TOKEN=[^ ]{8,}|ANTHROPIC_API_KEY=[^ ]{8,}|AKIA[0-9A-Z]{16}'
rc=0
for img in "$@"; do
  blob="$(docker image inspect "$img" --format '{{json .Config.Env}} {{json .Config.Labels}}' 2>/dev/null; docker history --no-trunc --format '{{.CreatedBy}}' "$img" 2>/dev/null || true)"
  if printf '%s' "$blob" | grep -Eq "$pattern"; then
    echo "  ✗ $img: token-shaped value in image ENV/labels/history" >&2; rc=1
  else
    echo "  ✓ $img: no token-shaped values in ENV/labels/history"
  fi
done
exit $rc
