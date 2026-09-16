#!/usr/bin/env bash
# Worker egress allowlist (DEP-S1-04).
#
#   scripts/k8s/egress-allowlist.sh resolve        # print the CIDRs the HF endpoints resolve to today
#   scripts/k8s/egress-allowlist.sh helm-args      # → --set flags enabling workers-egress-allowlist with those CIDRs
#   scripts/k8s/egress-allowlist.sh nft > /etc/nftables.d/notes-workers.nft   # host firewall for a compose/VM staging
#   scripts/k8s/egress-allowlist.sh test           # from inside the cluster/compose: worker must NOT reach example.com
#
# Allowed: HF endpoint hostnames (HF_CHAT_ENDPOINT_URL / HF_ASR_ENDPOINT_URL,
# the shared api front door endpoints.huggingface.cloud), Postgres,
# Redis, OTel collector, DNS. Everything else is dropped. Hostname rules
# need an FQDN-capable CNI (Cilium) — until the hosting decision the list
# is CIDR-based and must be re-resolved when HF rotates front-door IPs
# (alert ModelBackendUnavailable will tell you; runbook §unavailable).
set -euo pipefail
cmd="${1:-resolve}"
hosts=()
for url in "${HF_CHAT_ENDPOINT_URL:-}" "${HF_ASR_ENDPOINT_URL:-}"; do
  [ -n "$url" ] && hosts+=("$(printf '%s' "$url" | sed -E 's#^[a-z]+://##; s#[/:].*$##')")
done
hosts+=("api.endpoints.huggingface.cloud")

resolve() {
  for h in "${hosts[@]}"; do
    dig +short A "$h" 2>/dev/null | grep -E '^[0-9.]+$' | sed 's#$#/32#'
  done | sort -u
}

case "$cmd" in
  resolve) resolve ;;
  helm-args)
    i=0; args="--set networkPolicies.enabled=true --set networkPolicies.egress.enabled=true"
    while read -r cidr; do args="$args --set networkPolicies.egress.allowedCidrs[$i]=$cidr"; i=$((i+1)); done < <(resolve)
    echo "$args" ;;
  nft)
    cat <<NFT
# notes-ai worker egress allowlist — generated $(date -u +%FT%TZ) by scripts/k8s/egress-allowlist.sh
# Apply on the staging host: nft -f this-file. Workers live on the docker bridge WORKER_NET (default 172.30.0.0/16).
table inet notes_workers {
  set model_endpoints { type ipv4_addr; flags interval; elements = { $(resolve | paste -sd, -) } }
  chain forward {
    type filter hook forward priority 0; policy accept;
    ip saddr ${WORKER_NET:-172.30.0.0/16} ip daddr 10.0.0.0/8 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} ip daddr 172.16.0.0/12 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} ip daddr 192.168.0.0/16 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} udp dport 53 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} tcp dport 53 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} ip daddr @model_endpoints tcp dport 443 accept
    ip saddr ${WORKER_NET:-172.30.0.0/16} counter drop
  }
}
NFT
    ;;
  test)
    # Positive + negative: the worker reaches its HF host (TCP connect) but not example.com.
    ns="${NS:-notes-staging}"
    pod="$(kubectl -n "$ns" get pod -l app=asr-worker -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    if [ -n "$pod" ]; then run() { kubectl -n "$ns" exec "$pod" -- python3 -c "$1"; }
    else run() { docker compose exec -T asr-worker python3 -c "$1"; }; fi
    probe='import socket,sys; h=sys.argv[1]
try:
    socket.create_connection((h,443),timeout=5); print("reachable")
except Exception as e: print("blocked", type(e).__name__)'
    blocked="$(run "$probe" example.com 2>/dev/null || true)"
    case "$blocked" in *blocked*) echo "  ✓ example.com blocked";; *) echo "  ✗ example.com REACHABLE — egress allowlist not enforced" >&2; exit 1;; esac
    for h in "${hosts[@]}"; do
      out="$(run "$probe" "$h" 2>/dev/null || true)"
      case "$out" in *reachable*) echo "  ✓ $h reachable";; *) echo "  ✗ $h blocked: $out" >&2; exit 1;; esac
    done ;;
  *) echo "usage: $0 resolve|helm-args|nft|test" >&2; exit 2 ;;
esac
