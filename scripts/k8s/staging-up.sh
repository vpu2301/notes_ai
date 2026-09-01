#!/usr/bin/env bash
# ── Bring up the k3d STAGING cluster ──────────────────────────────────
#
# Stands up the full product on a local k3d cluster from the locally
# built compose images (the fallback posture while the hosting decision
# is pending — docs/deploy/hosting-gap.md). Same chart, same gates,
# laptop-sized cluster.
#
#   scripts/k8s/staging-up.sh            # create + deploy everything
#   scripts/k8s/staging-up.sh --delete   # tear the cluster down
#
# Prereqs: k3d, helm, kubectl, docker; compose images built.
# RAM: stop the compose app stack first (docker compose stop).

set -euo pipefail
cd "$(dirname "$0")/../.."

CLUSTER=notes-staging
NS=notes-staging

if [[ "${1:-}" == "--delete" ]]; then
  k3d cluster delete "$CLUSTER"
  exit 0
fi

# 1. Cluster. Traefik is DISABLED — nothing in the namespace is meant to
#    be reachable from outside the cluster (public exposure is a hosting
#    decision, docs/deploy/hosting-gap.md).
if ! k3d cluster list | grep -q "^$CLUSTER"; then
  k3d cluster create "$CLUSTER" \
    --agents 1 \
    --k3s-arg "--disable=traefik@server:0" \
    --wait
fi

# 2. Import the locally built images (no registry in staging) + the
#    stateful/utility images the chart pins.
docker pull pgvector/pgvector:pg16 >/dev/null || true
docker pull busybox:1.36 >/dev/null || true
IMAGES=(
  notes-ai-auth-service:latest
  notes-ai-asr-service:latest
  notes-ai-asr-worker:latest
  notes-ai-dictation-service:latest
  notes-ai-nlp-service:latest
  notes-ai-note-service:latest
  notes-ai-autocomplete-service:latest
  notes-ai-generation-service:latest
  notes-ai-notification-service:latest
  notes-ai-migrate:latest
  notes-ai-seed:latest
  pgvector/pgvector:pg16
  busybox:1.36
)
k3d image import -c "$CLUSTER" "${IMAGES[@]}"

# 3. Namespace + out-of-band material (secret VALUES never live in the chart).
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic mdx-postgres \
  --from-literal=password=postgres --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic mdx-minio \
  --from-literal=user=minioadmin --from-literal=password=minioadmin \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic mdx-keycloak-admin \
  --from-literal=user=admin --from-literal=password=admin \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic mdx-keycloak-clients \
  --from-literal=KEYCLOAK_LOGIN_CLIENT_SECRET=dev-secret-change-in-prod-mdx-backend \
  --from-literal=KEYCLOAK_ADMIN_CLIENT_SECRET=dev-secret-change-in-prod-mdx-admin \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic mdx-master-key \
  --from-file=master.key=infra/dev/master.key \
  --dry-run=client -o yaml | kubectl apply -f -

# Realm import (staging: the dev realm export; production: the realm is
# produced by scripts/k8s/gen-prod-realm.py).
kubectl -n "$NS" create configmap mdx-keycloak-realm \
  --from-file=realm-export.json=infra/keycloak/realm-export.json \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Deploy. The post-install hooks run migrate (with the idempotent
#    init.sql initContainer) → minio-init → seed.
helm upgrade --install notes infra/k8s/notes -n "$NS" --timeout 15m "$@"

echo "staging-up: deployed. kubectl -n $NS get pods"
echo "KEDA (optional): helm install keda kedacore/keda -n keda --create-namespace"
echo "                 helm upgrade notes infra/k8s/notes -n $NS --set keda.enabled=true"
