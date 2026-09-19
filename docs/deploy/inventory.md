# Deployment — compose → cluster inventory

Every service, volume and cron the compose stack runs today, and its
cluster counterpart in the `infra/k8s/notes` chart. Nothing is migrated
silently; the deliberate non-migrations are justified inline.

## Application services (9)

| Compose service | Cluster counterpart | Notes |
|---|---|---|
| auth-service | Deployment+Service `auth-service` | HPA-eligible (prod 2–6 replicas) |
| asr-service | Deployment+Service `asr-service` | |
| asr-worker | Deployment `asr-worker` (no Service — stream consumer) | prod: GPU pool, one pod/GPU |
| dictation-service | Deployment+Service `dictation-service` | GPU pool (prod), 2 Gi per-pod tmpfs, preStop drain, grace 1830 s, KEDA weighted scaling |
| nlp-service | Deployment+Service `nlp-service` | HPA-eligible |
| note-service | Deployment+Service `note-service` | |
| autocomplete-service | Deployment+Service `autocomplete-service` | |
| generation-service | Deployment+Service `generation-service` | staging: layer C off (no llama backend in k3d) |
| notification-service | Deployment+Service `notification-service` | consumer name = pod name (downward API) |

## Infra

| Compose | Cluster counterpart | Notes |
|---|---|---|
| postgres | staging: StatefulSet+PVC; prod: CloudNativePG / managed (hosting-gap.md) | init.sql roles via ConfigMap |
| redis | staging: Deployment; prod: Redis operator / managed | |
| keycloak | staging: Deployment (dev realm import); prod: realm from `gen-prod-realm.py` (regenerated secrets, no dev users) | |
| kafka | **NOT MIGRATED** — no service consumes it; libs/messaging is Redis Streams. Legacy compose infra; drop. | |
| otel-collector | Deployment `otel-collector` | OTLP → Prometheus exposition |
| prometheus | staging: Deployment (KEDA + product metrics); prod: kube-prometheus-stack (observability.md) | |
| grafana / jaeger / loki | **staging: not deployed** (laptop budget); prod: kube-prometheus-stack + Tempo/Loki per observability.md | dashboards/alerts live in repo, mounted there |
| mailpit | Deployment `mailpit` (staging); prod: real SMTP relay | |
| llama-server | staging: disabled; prod: GPU-pool Deployment (hosting-gap.md) | |

## One-shots & crons

| Compose / host cron | Cluster counterpart |
|---|---|
| migrate (one-shot) | Helm hook Job `mdx-migrate-<rev>` (post-install/upgrade) |
| seed (one-shot) | Helm hook Job `mdx-seed-<rev>` — **staging only**, `jobs.seed.enabled=false` in prod |
| nightly-verify.cron | CronJob `mdx-nightly-verify` |

The cron script ships in the chart (`files/jobs/`), drift-gated against
`scripts/jobs/` by `check-k8s-rendered`, and runs on the note-service
image (carries every lib it imports).

## Volumes

| Compose volume | Cluster counterpart |
|---|---|
| postgres_data | PVC (staging); operator-managed (prod) |
| redis_data | staging: emptyDir + AOF (cache + streams tolerate pod loss; prod operator adds persistence) |
| kafka_data | dropped with kafka |
| prometheus/grafana/loki data | kube-prometheus-stack PVCs (prod) |
| host tmpfs `/run/dictation` (shared, 2 g) | **per-POD** `emptyDir medium: Memory, sizeLimit: 2Gi` — the §tmpfs-pressure fix |
| infra/dev/master.key bind-mounts | Secret `mdx-master-key` (staging script / ExternalSecret→Vault prod) |
| HF-cache model mounts (large-v3) | **prod: baked in images** (house pattern, PINS.md); staging k3d uses the baked tiny |

## Trusted proxies (`TRUSTED_PROXY_CIDRS`)

auth-service and, since Sprint 19, note-service key their per-IP abuse
caps on the client address. `X-Forwarded-For` is believed only when the
TCP peer is inside `TRUSTED_PROXY_CIDRS` (comma-separated; empty means
the peer is the client). In k8s (`infra/k8s/notes`) set it to the
ingress controller's pod/network CIDR on BOTH services; left empty
behind an ingress, every reader of `/v1/shared/*` shares one bucket and
`SharedPageRateLimitHigh` fires.

## Public API hostname for recipient mail (Sprint 22)

Recipient links point at the web app (`MDX_APP_BASE_URL`), but the
unsubscribe link in every recipient mail points at note-service:
`MDX_API_PUBLIC_BASE_URL` + `/v1/shared/unsubscribe/…`. The
`/v1/shared/*` routes must therefore be reachable on a public hostname
(they are anonymous and rate-limited by design). Set both variables per
environment; the dev defaults are `localhost`.

## External sharing flags and rollout (Sprint 23)

Flags per environment: `MDX_EXTERNAL_SHARING_ENABLED`,
`MDX_RECIPIENT_ACTIONS_ENABLED`, `MDX_SIGNUP_ENABLED`, the
`MDX_SHARE_MAIL_*_PER_DAY` caps and `MDX_SHARE_RETENTION_DAYS`. Stages
and exit criteria: `docs/runbooks/external-sharing.md`.

`/v1/shared/*` is served cross-origin without credentials
(`AnonymousCorsMiddleware`), so it may sit behind a public hostname that
differs from the SPA's; every other route keeps the credentialed
allow-list. No Ingress objects exist in the chart yet; the public
exposure of note-service's `/v1/shared/*` and the SPA's `/s/*` is an
environment-level decision to record here when made.
