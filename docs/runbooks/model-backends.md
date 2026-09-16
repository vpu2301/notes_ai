# Runbook — model backends (`libs/models`, HF Inference Endpoints, job warming)

Scope: the chat/ASR backends resolved from `config/models.yaml` (`hf_eu`,
`hf_eu_asr` on staging/beta; `dev_mac*` on the founder's Mac; `hosted_eu`
dormant), the `waiting_on_model` job state, the `model_usage` ledger and
the HF token. Alerts: `infra/prometheus/rules/model-backends.yml`.
Endpoint specs: `deploy/hf/endpoints/`. Design: ADR-0046.

| Concern | Path / command |
|---|---|
| Backend registry | `config/models.yaml`, `libs/models/` |
| Endpoint specs / apply | `deploy/hf/endpoints/*.yaml`, `make hf-endpoints ARGS="status --env staging"` |
| Queue + warming | `libs/jobs/` (`jobs` table, migration 0022), `jobs_waiting_by_backend()` |
| Usage ledger | `model_usage`, `model_usage_daily` (0023), rates `config/model_costs.yaml` |
| Secrets | `HF_TOKEN`, `HF_CHAT_ENDPOINT_URL`, `HF_ASR_ENDPOINT_URL`, `HF_*_MODEL_PIN` — k8s secret `mdx-hf-endpoints` (staging: `scripts/k8s/staging-up.sh`; prod: External Secrets ← Vault) |
| Egress | `scripts/k8s/egress-allowlist.sh`, `workers-egress-allowlist` NetworkPolicy |
| Dev Mac | `docs/dev/models-on-mac.md`, `make dev-model` |

## warming-too-long

`ModelBackendWarmingTooLong{backend}`: jobs parked in `waiting_on_model`
for more than 2 × the backend's `cold_start_seconds`. Normal wake-up is
1–5 min and consumes no attempt; this alert means the endpoint is not
coming up.

1. `make hf-endpoints ARGS="status --env staging"` — state should be
   `running`/`scaledToZero`. `failed`/`initializing` for > 10 min → step 3.
2. `SELECT waiting_backend, count(*), min(waiting_since) FROM jobs WHERE status='waiting_on_model' GROUP BY 1;`
   (as a superuser; `app_role` sees one tenant).
3. `make hf-endpoints ARGS="plan --env staging"` — drift (someone resized
   in the console, a revision that no longer exists) shows here. Re-apply
   from the spec via the **HF endpoints — apply** workflow. If the HF
   region itself is degraded → §region-outage.
4. Jobs recover on their own once `probe()` succeeds; after the warming
   budget they fall back to normal retries (attempt consumed) and, past
   `max_attempts`, `dead` → §dead-jobs.

## auth

`ModelBackendAuth{backend}`: calls fail with `kind=auth`. Jobs fail
immediately (`failed`, not retried) — a revoked token must never cause a
retry storm.

1. Confirm: the worker log line `jobs.model_backend_auth` / `model_usage`
   rows with `error_kind='auth'`. The token value never appears in logs or
   `ProviderError` text (redaction test) — do not go looking for it there.
2. Restore or rotate (§token-rotation). Restart the workers (the token is
   read at startup). Verify: `make eval-smoke ENV=staging BACKEND=hf_eu`.
3. Re-queue the failed jobs: `UPDATE jobs SET status='queued', run_at=now(), attempts=0 WHERE status='failed' AND error_kind='auth';`
   (superuser; per-tenant via `tenant_connection` otherwise).

## unavailable

`ModelBackendUnavailable{backend}`: every call for 10 min failed with
`kind=unavailable` (connection refused, 5xx, endpoint deleted). Jobs are
retrying with backoff (15 s → 15 min); notes ship transcript-only until
the backend returns (BE-S2 degrade).

1. `status` as above. `absent` → someone deleted it: `apply` recreates it
   from the spec (URL changes → update the `mdx-hf-endpoints` secret →
   restart workers).
2. Endpoint fine but unreachable from the workers only → the egress
   allowlist is stale (HF rotated front-door IPs):
   `scripts/k8s/egress-allowlist.sh resolve`, re-apply with
   `helm upgrade … $(scripts/k8s/egress-allowlist.sh helm-args)`, then
   `make test-egress`.
3. Region-wide → §region-outage.

## region-outage

HF status page shows the EU region down. Options, cheapest first:

1. Wait: jobs back off up to 15 min per attempt and consume attempts
   slowly; raise `max_attempts` for the affected kinds if the outage is
   long (`UPDATE jobs SET max_attempts = 20 WHERE status IN ('queued','waiting_on_model')`).
2. Re-create the endpoints in a second EU region from the same specs:
   edit `provider.region` (must stay `eu-*`), run **apply**, update the
   URLs in the secret, restart workers. Processor on the Data page stays
   "Hugging Face Inference Endpoints, EU" — no notice needed.
3. Never route to `dev_mac` or to a non-EU region as a workaround: the
   registry refuses both at startup by design (decision 12).

## dead-jobs

`ModelJobsDead{kind}`: a job exhausted `max_attempts` or lost its worker
repeatedly. `SELECT id, tenant_id, kind, attempts, error_kind, last_error FROM jobs WHERE status='dead' ORDER BY finished_at DESC;`
Fix the cause (this runbook, or the job's own runbook), then re-queue:
`UPDATE jobs SET status='queued', run_at=now(), attempts=0 WHERE id = …`.
`error_kind='worker_lost'` with a healthy backend = a worker OOM/crash
loop: check the pod, not the model.

## token-rotation

`HF_TOKEN` is a fine-grained token scoped to *Inference Endpoints* for one
namespace, one per environment. Rotate quarterly and on any suspected
exposure.

1. Create the new token in the HF org settings (scope: Inference Endpoints
   read+write on the namespace; nothing else). Never a classic
   write-all token.
2. Staging: export the new value and re-run `scripts/k8s/staging-up.sh`
   (re-creates `mdx-hf-endpoints`), then `kubectl -n notes-staging rollout restart deploy/asr-worker`.
   Prod: update the Vault path the External Secret reads; ESO syncs the
   secret; roll the workers.
3. Verify: `make eval-smoke ENV=staging BACKEND=hf_eu`; alert
   `ModelBackendAuth` stays silent.
4. Revoke the old token. Update `HF_TOKEN_STAGING` in GitHub secrets (used
   only by the `hf-endpoints-plan` job).
5. If the old token may have leaked: `make secret-scan` on the repo; check
   HF audit log for endpoint changes; rotate again after the incident.

## pin-upgrade

Changing `model.revision` (or the model) in a spec is a model change:

1. Update `docs/models/PINS.md` (row + fetch date) and the spec.
2. `make hf-endpoints ARGS="plan --env staging"` in the PR shows the diff.
3. `make eval-smoke ENV=staging BACKEND=hf_eu` before and after; DEP-S4
   turns this into the CI eval gate. No metric may regress > 1 pp.
4. Apply via the workflow; watch `ModelBackendWarmingTooLong` for the
   first wake-up (a new image can take longer).

## keep-warm

Off by default (`KeepWarmSchedule(enabled=False)`, `libs/jobs/keepwarm.py`).
Enabling it on staging costs the instance's hourly rate 11 h × 5 days a
week; the decision for prod is DEP-S6 with the cost model. To try it on
staging: set the worker's keep-warm flag, watch
`mdx_model_keepwarm_probes_total` and `model_usage_daily.cost_cents_est`.

## ask-this-note

`POST /v1/notes/{id}/ask` (the chat bar under a note in the Mac app) is
served by **note-service**, not a worker: one `chat.complete` per question
over the note's current version plus its transcript (fetched from
asr-service with the caller's bearer). Route: `routing.understand` in
`config/models.yaml` (dev: the Mac's Ollama `notes-chat`; staging/prod:
`hf_eu`). Nothing is stored; the client keeps the thread and sends the last
12 turns back as context. Audit: `note.asked` with backend, model id and
character counts only.

Symptoms → cause:

- `503 model_not_configured` — the registry could not resolve a chat
  backend: on staging `mdx-hf-endpoints` lacks `HF_CHAT_ENDPOINT_URL` /
  `HF_TOKEN` / `HF_CHAT_MODEL_PIN`; on a dev Mac Ollama is down or the
  `notes-chat` model is missing (`make dev-model`).
- `503 model_unavailable` (`kind` names the class: `warming`, `timeout`,
  `rate_limited`, …) — the backend answered badly; see the sections above
  for that kind. The note itself is unaffected.
- Answers ignore the recording — asr-service refused the transcript
  (410 erased, 403, or down); the handler logs `ask.transcript_unavailable`
  and answers from the note text alone by design.

Egress: note-service is deliberately not under `workers-egress-allowlist`
(it must reach asr-service and calendar feeds). The model call therefore
leaves the cluster without the CIDR allowlist that protects the workers —
tracked as an open decision (widen the policy for app-tier peers, or move
the call into a `libs/jobs` worker).

## Pre-flight after deployment

- `make hf-endpoints ARGS="plan --env staging"` → no drift.
- `make eval-smoke ENV=staging BACKEND=hf_eu` → 5/5, hallucination 0.
- `make test-egress` → example.com blocked, endpoints reachable.
- `SELECT * FROM model_usage_daily ORDER BY day DESC LIMIT 5;` shows rows for `hf_eu` / `hf_eu_asr`.
