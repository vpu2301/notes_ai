# Deployment — the hosting gap (what awaits the human's decision)

The chart (`infra/k8s/notes`) was built and LIVE-VERIFIED against a local
k3d cluster (the fallback while the hosting decision is pending).
Everything below is what changes per the concrete choice; each row names
the artefact that absorbs it. Nothing else in the chart depends on the
choice.

| Gap | Cluster artefact | What the decision picks |
|---|---|---|
| Cluster itself | — | on-prem k3s/RKE2, or a managed cloud region |
| GPU node pool | `values-prod.yaml` (`mdx-pool: gpu` selector, `gpu=true:NoSchedule` taint, `nvidia.com/gpu` resources) | node provisioning + NVIDIA device plugin install |
| Stateful stores | `stateful.inCluster=false` + DSN/hosts in values | CloudNativePG / Redis operator / MinIO operator, or managed equivalents |
| Public ingress + TLS | none in-chart — nothing in the namespace is internet-reachable | the provider's ingress/LB + cert issuance in front of the SPA/API, plus WAF/CDN if wanted |
| Vault endpoint | `MDX_VAULT_ADDR`, ExternalSecrets ClusterSecretStore | the production Vault (same trust root as ADR-0011 KMS) |
| Registry | `global.imageRegistry` | a registry close to the cluster (multi-GB model-baked images) |
| NetworkPolicy CNI | `networkPolicies.enabled=true` (prod) | **named gap, found live**: k3d/k3s v1.35's embedded netpol controller enforces default-deny but drops the allow rules — the policies are standard v1 semantics and must be verified on the real CNI (Calico/Cilium) at cluster bring-up |
| Ingress controller | k3s bundles Traefik; staging disables it (nothing to expose) | per distribution |
| llama-server (Layer C) | `stateful.llamaServer` disabled in staging | GPU-pool deployment + model blob provisioning |

## Staging↔prod parity notes (found during the live bring-up)

- `pgvector/pgvector:pg16` is REQUIRED (init.sql `CREATE EXTENSION
  vector`); plain postgres aborts first boot and leaves a half-init
  store. The migrate hook re-applies init.sql idempotently as an
  initContainer, so the store self-heals either way.
- Secret-mounted master key: fsGroup would give 0440 (provider refuses),
  no fsGroup gives root-owned 0400 (unreadable) — the root initContainer
  copy is the pattern (apps.yaml comment).
- Sprig `default` treats `false` as empty — boolean opt-outs in values
  must be checked with `hasKey`, never `| default true`.
