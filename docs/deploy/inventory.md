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
| — | CronJob `mdx-ai-retention` (Sprint 37): terminal `jobs` after 30 days, `model_usage` after 400. Runs as **tenant_writer**, the only role allowed to delete from either (migration 0054) |

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

## Diarization endpoint (ADR-0052 shape B)

| Thing | Where |
|---|---|
| Image | `deploy/diar-server` → `ghcr.io/notes-ai/diar-server:{tag}` (built with the gated-model BuildKit secret) |
| Endpoint | `deploy/hf/endpoints/diar.yaml` — AWS `eu-west-1`, T4, `min_replica: 0` |
| Backend | `hf_eu_diar` in `config/models.yaml` (dev: `dev_mac_diar` on the Mac) |
| Secrets | `HF_DIAR_ENDPOINT_URL`, `HF_TOKEN` (worker side, k8s secret `mdx-hf-endpoints`); `MDX_DIAR_SERVER_TOKEN` — the SAME value on both sides: the worker sends it as `X-MDX-Diar-Token` and the server refuses to start without it. The HF bearer is separate and satisfies the gateway only |
| Worker switch | `MDX_DIAR_ENGINE=http`, `MDX_DIAR_HTTP_BACKEND=hf_eu_diar`; rollback `legacy` |
| Egress | one new destination, in `scripts/k8s/egress-allowlist.sh`; hub and pyannote telemetry stay blocked |
| Processor disclosure | the backend's `processor:` entry (Hugging Face Inference Endpoints, EU) reaches the workspace Data page like ASR's |

Cost, order of magnitude: a scale-to-zero T4 at ~$0.50–0.75 per GPU-hour
and ~0.15 × audio is roughly **$0.07–0.11 per audio-hour** plus idle and
cold starts. Measure it against the real bill before quoting it.

## Mistral AI (EU) — hosted chat model (Sprint L2, SQ1 T5)

The processor half is in `docs/legal/third-party-notices.md` (zero data retention,
training opt-out, DPA, Data-page acknowledgement). This is the operational half.

| Thing | Where |
|---|---|
| Backends | `mistral_eu` (`mistral-large-2512`, writing: `understand`/`summarize`) and `mistral_eu_small` (`mistral-small-2603`, `classify`/`title`/`entities`) in `config/models.yaml`. Today they are routed in **dev only** (`env_overrides.dev`). Staging and prod route `hf_eu` until ADR-0068 is accepted for Mistral. |
| Endpoint | `https://api.mistral.ai/v1` (`MISTRAL_API_URL`), EU hosting |
| Secrets | `MISTRAL_API_KEY`, one key per environment, in k8s secret `mdx-model-keys` (staging/prod) and `.env` (dev). Never in the web bundle and never in a log. The startup probe fails the service when it is missing (`missing_env`) and falls back in dev only. Pins: `MISTRAL_LARGE_PIN`, `MISTRAL_SMALL_PIN` (dated ids, never `-latest`) |
| Egress | one destination, `api.mistral.ai:443`, added to `scripts/k8s/egress-allowlist.sh` when staging routes it |
| Cost | `config/model_costs.yaml`: Large 0.05 / 0.15 cents per 1k input / output tokens; Small 0.015 / 0.06 (read 2026-09-27). Per meeting-hour: **not measured on real recordings** (SQ1 T3 needs `eval/notes/v2`). Reports carry it from `model_costs.yaml` |
| Plan | Mistral Pro (active since 2026-09-28) |
| Rollback | revert the routing PR; `hf_eu` stays deployed |

## Parakeet ASR candidate (Sprint TQ4, ADR-0067)

| Thing | Where |
|---|---|
| Image | `deploy/asr-server` → `ghcr.io/notes-ai/asr-server:{tag}` (NeMo, weights baked and sha256-checked) |
| Endpoint | `deploy/hf/endpoints/asr-parakeet.yaml`: `notes-asr-parakeet-{env}`, `eu-west-1`, T4, `min_replica: 0` |
| Backend | `cand_parakeet_asr` (not routed); worker shadow via `MDX_ASR_SHADOW_BACKEND` |
| Secrets | `CAND_PARAKEET_URL`, `HF_TOKEN` (gateway); `MDX_ASR_SERVER_TOKEN` on the server, which is the same value as the worker's `CAND_PARAKEET_SERVER_TOKEN`, sent as `X-MDX-ASR-Token` |
| Cost | scale-to-zero T4. Per audio-hour: **not measured** (no endpoint raised yet) |

## Diarization capacity (Sprint 32)

Measured on an Apple M5 CPU (not a cluster node; re-measure on the worker
shape): the legacy engine diarizes at **0.016–0.024 × audio**, so one worker
replica's diarization step alone covers roughly **1,000–1,500 audio-hours per
day** if it did nothing else. In practice Whisper dominates the job (the ASR
pass, not diarization, sets throughput); diarization adds ~2 % wall time per
diarized job and **~1.7 GB RSS on a 2-hour recording** (3.0 GB for a 2-hour
dual-channel capture before the engine passes — size dual-channel workers for
≥ 4 GiB). Re-runs (`task=rediarize`) cost one diarization pass, no ASR. Staging
numbers: docs/testing/load/speakers-2026-09-19.md (scenarios 1/2/5 pending).

**Diarizer v2 changes this picture** (measured 2026-09-20, same Mac):
community-1 runs at **0.64–0.85 × audio on four CPU threads** and
0.13–0.15 × on the Mac's GPU — which is why it runs on an endpoint (above) rather
than inside the worker. A worker on `MDX_DIAR_ENGINE=http` spends its own
time only on the upload and the wait, so worker sizing stays as measured
for the legacy engine; the GPU capacity is the endpoint's `max_replica`.

## Note generation (Sprint 37)

| What | Where |
|---|---|
| Secrets | the bake-off candidates read the same `HF_TOKEN` as `hf_eu` plus a per-candidate `CAND_*_URL`; a premium candidate adds `CAND_FRONTIER_TOKEN`. Per environment, never in the web bundle, never in a log |
| Worker | `note-worker`: same image as note-service, `python -m note_service.worker`. Two jobs at a time per replica, at most `MDX_NOTE_GENERATION_PER_TENANT` (3) from one workspace |
| Snapshots | `tenant/{tid}/generation/*.json.enc` in the transcripts bucket — deleted at the end of every run, swept daily, and nothing older than `MDX_NOTE_GENERATION_SNAPSHOT_HOURS` (24) may exist |
| Shadow runs | `MDX_NOTE_GENERATION_SHADOW_BACKEND` + `_PERCENT` on the worker only. Output is discarded; only counts are kept |

**Capacity: not measured.** A generation is `ceil(minutes / ~6000 chars)`
windows of extraction plus one reduce, so throughput is the backend's
tokens per second and not ours — which is exactly why the line has to be
measured on the environment that will serve the pilot rather than guessed
here. `docs/testing/load/notes-README.md` scenario `burst` produces it:
meeting-hours per day per worker replica per tier.
