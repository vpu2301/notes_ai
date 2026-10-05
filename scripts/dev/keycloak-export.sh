#!/usr/bin/env bash
# Re-export the realm from the running Keycloak container into
# infra/keycloak/realm-export.json. Diff before committing: the export adds
# many auto-generated IDs.
set -euo pipefail

REALM="${REALM:-notes}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
OUT="${OUT:-infra/keycloak/realm-export.json}"

# Container path that Keycloak uses for one-off exports.
TMP_IN_CONTAINER="/tmp/realm-export.json"

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "Exporting realm '${REALM}' from running Keycloak container..."
docker compose -f "${COMPOSE_FILE}" exec -T keycloak \
    /opt/keycloak/bin/kc.sh export \
        --dir /tmp/export \
        --realm "${REALM}" \
        --users realm_file >/dev/null

docker compose -f "${COMPOSE_FILE}" exec -T keycloak \
    sh -c "cat /tmp/export/${REALM}-realm.json" > "${OUT}.tmp"

mv "${OUT}.tmp" "${OUT}"
echo "Realm exported to ${OUT}"
echo "Review the diff carefully — Keycloak includes generated IDs that will churn the file."
