# Runbook — asr-worker

Single-page operations guide for the sprint-03 GPU worker.

## Key paths

| Concern               | Path / command                                     |
| --------------------- | -------------------------------------------------- |
| Service code          | `services/asr-worker/`                             |
| Master key (dev)      | `/etc/mdx/master.key` (mounted from `infra/dev/`)  |
| Queue                 | Redis stream `asr:jobs`, group `asr-workers`       |
| DLQ                   | Redis stream `asr:jobs:dlq`                        |
| Audio bucket          | S3 `mdx-audio`                                     |
| Transcript bucket     | S3 `mdx-transcripts`                               |
| Dashboard             | Grafana → "Sprint 03 — ASR Health"                 |
| Alerts                | `infra/prometheus/rules/sprint-03-asr.yml`         |

## Failure modes

### § master-key-missing

The worker refuses to start because `/etc/mdx/master.key` is missing.

1. Confirm volume mount: `docker compose exec asr-worker ls -l /etc/mdx`.
2. If the file is absent in dev, re-create it:
   ```sh
   openssl rand 32 > infra/dev/master.key
   chmod 0400 infra/dev/master.key
   ```
3. In staging/prod a missing master key is a **security incident** —
   page security lead immediately; do not invent a new key.

### § master-key-permissions

Mode is more permissive than 0400. `chmod 0400` the file and restart.
In staging/prod treat as an incident — the file should never have been
group/other-readable.

### § gpu-oom

Symptoms: `mdx_asr_oom_total` increments; jobs land in `failed` with
`error_kind='gpu_oom'`.

1. Identify the offending job via traces (audio_seconds, segments).
2. If a single tenant is sending unusually long audio, reduce beam size:
   set `MD_ASR_BEAM_SIZE=3` and bounce one replica to confirm the
   reduction holds.
3. If the OOM persists with beam_size=3 on a 30-min file, reduce the
   max audio length cap (`MD_ASR_MAX_DURATION_SECONDS`) until we ship
   chunk-streaming inference (sprint 04).

### § model-corruption

Symptoms: `mdx_asr_model_loaded=0`; worker logs "checksum mismatch".

1. Delete the cached weights: `docker compose exec asr-worker rm -rf /root/.cache/huggingface`.
2. Restart the worker.

### § queue-backlog

Symptoms: `mdx_asr_queue_depth > 100` for > 5 m.

1. Scale workers: `docker compose -f base.yml -f dev.yml -f gpu.yml up -d --scale asr-worker=N`.
2. If the upstream rate is sustained, the capacity model is wrong;
   open a follow-up to revise the sprint-16 sizing ADR.

### § object-store-outage

Symptoms: jobs queue but don't progress; worker log says
`storage.s3.head_bucket_failed`.

1. Confirm the object store is reachable from the worker (S3_ENDPOINT).
2. Recover it; jobs resume automatically because they remain in the
   pending-entries list until reclaimed.

### § nvidia-driver-mismatch

Symptoms: container fails to start; `nvidia-container-cli` errors.

1. `nvidia-smi` on the host — should match the CUDA version in the
   `cuda:12.4.1-cudnn-runtime-ubuntu22.04` base image (driver ≥ 535).
2. Upgrade the host driver or downgrade the worker base image (rare).

### § stranded-jobs (worker_lost / queue_lost / retry_exhausted)

Symptoms: jobs stuck in `running` or `queued` long after the recording
could have finished; a tenant hitting `concurrency_exceeded` on upload
with no visible activity (every stranded row burns a slot in
`MD_ASR_PER_TENANT_CONCURRENT_JOBS`).

The worker is the only writer of a job's terminal status, and it cannot
write one for the crash that killed it. Two backstops close that gap —
the DLQ path (`retry_exhausted`) and the reaper in **asr-service**
(`worker_lost` for `running`, `queue_lost` for `queued`). Full vocabulary:
`docs/api/asr-job-errors.md`.

1. Check the reaper is running at all: `asr.job_reaper_swept` in
   asr-service logs, and `MD_ASR_JOB_REAPER_ENABLED` (default true).
2. Check the DLQ: `XLEN mdx.asr.jobs:dlq`. Entries carry
   `x-final-error-kind` — that is the failure that kept repeating.
3. If jobs are being reaped that were merely slow (a reaped job whose
   audio is long), the grace window is too tight. It must exceed
   `MD_ASR_MAX_DURATION_SECONDS × MD_ASR_MAX_INFERENCE_SECONDS_MULTIPLIER`
   plus a redelivery; raise `MD_ASR_JOB_REAPER_RUNNING_GRACE_S`.
4. Reaping is safe to re-run and never overwrites a finished job: the
   update is conditional on the status the sweep scanned.

### § speaker-overcount

`DiarizationSpeakerOvercount`: over 25 % of diarized jobs in 24 h have 5+
speakers. Read `metadata.diarization` on recent rows:

```sql
SELECT id, metadata->'diarization' FROM transcription_jobs
WHERE metadata ? 'diarization' ORDER BY finished_at DESC LIMIT 20;
```

- `clusters_raw` ≫ `speakers` with a large `clusters_dropped`: the floor is
  working; the extra speakers survived it. Look at `speaker_speech_seconds`
  — a tail of labels with a few seconds each is phantom speakers.
- `unknown_share` > 0.15: speech the clusterer could not place (crosstalk,
  far field). Expect wrong or missing labels more than extra ones.
- Compare against the gold set: `make der-eval ENGINE=legacy SPLIT=test`.
Users fix a bad split with Merge in any client; nothing to do per job.

### § diarization-engine (switch, shadow, rollback)

Sprint 29 put the diarizer behind a seam (`libs/diarization/protocol.py`).
The worker logs `diarization.engine_selected {engine, shadow_engine}` at
startup — it has no readiness endpoint, so that line is how to confirm a
pod's engine.

| Setting | Values | Effect |
| --- | --- | --- |
| `MDX_DIAR_ENGINE` | `legacy` (default) \| `pyannote` \| `http` | Engine for every diarized job and re-run. `http` = the GPU endpoint (ADR-0052 shape B, § diarization-endpoint). An unknown value fails startup. |
| `MDX_DIAR_SHADOW_ENGINE` | empty \| `legacy` \| `pyannote` | Also runs this engine AFTER the job is complete and announced; its labels are discarded. Emits `mdx_asr_diarization_shadow_delta` and logs `diarization.shadow`. Failures only log `diarization.shadow_failed`. |
| `MDX_DIAR_V2_MODEL_DIR` / `_MODEL_REPO` / `_MODEL_REVISION` / `_PINS` | baked dir / repo / revision / JSON filename→sha256 | community-1 weights, verified before load (fail-closed). |
| `MDX_DIAR_V2_BATCH` | 0 = 16 CPU / 32 GPU | Windows embedded at once; lower it if a worker OOMs on long recordings. |
| `MDX_DIAR_MIN_SPEAKER_SPEECH_MS` / `_SHARE` | 8000 / 0.03 | Roster guard floor, every engine. Both 0 = grade the count, dissolve nothing. In shape B it travels with each request, so the policy stays the worker's. |
| `MDX_DIAR_HTTP_BACKEND` | empty \| a `diar_http` backend in `config/models.yaml` | Which endpoint `http` calls. Empty = the env's `diarization` override (dev → `dev_mac_diar`, staging/prod → set it to `hf_eu_diar`). |
| `MDX_DIAR_SERVER_TOKEN` | the diar-server's own token | Sent as `X-MDX-Diar-Token`. The endpoint gateway eats `Authorization`, so the container needs its own; empty = the backend's bearer is sent in both places. A wrong value is caught at startup — the health check reports `authenticated: false` and the worker refuses the engine. |
| `MDX_DIAR_HTTP_SECONDS_PER_AUDIO_SECOND` | 0.5 | Timeout budget per second of audio. Fits a GPU endpoint (~0.15 ×); raise it above 0.85 for a CPU-hosted one or every recording times out. |

- **Rollback** = set `MDX_DIAR_ENGINE=legacy` and restart workers; no other
  service deploys. `metadata.diarization.engine` on each job says which
  engine produced it; old jobs can be re-run on demand with today's engine.
- **v2 refuses to load** (`diarization_unavailable`, retryable) when
  `PYANNOTE_METRICS_ENABLED` is not `false` or `HF_HUB_OFFLINE` is not `1`
  (`last_error` = `telemetry_not_disabled` / `hub_not_offline`). The worker's
  `config.py` pins both at import; something overrode them after start.
  Never "fix" this by unsetting the check — it is what keeps the worker
  from posting to `otel.pyannote.ai`.
- **v2 digest mismatch / missing dir**: same retryable failure; rebuild the
  image (`make prepare-pyannote` on dev boxes) or flip to `legacy`.

### § diarization-endpoint (shape B)

Since ADR-0052 the diarizer runs on its own GPU endpoint
(`deploy/diar-server`, spec `deploy/hf/endpoints/diar.yaml`, backend
`hf_eu_diar`). The worker posts audio and gets labelled spans back; the
engine inside the endpoint is the same one shape A would run in-process.

| Symptom | What it means | Do |
| --- | --- | --- |
| Jobs complete but have **no speakers**, `diarization_status='failed'` with `diarization_error='diarization_unavailable'` | The endpoint was unreachable or refused the token. **This is the designed behaviour** — the transcript is never held hostage to the diarizer. | `make hf-endpoints ARGS="status --env staging"`; check `HF_DIAR_ENDPOINT_URL` and the token; when it is back, the affected jobs re-label on demand (`POST /asr/jobs/{id}/rediarize`) — the clients offer it. |
| `diarization_error='diarization_failed'` on many jobs | The endpoint answered, but the run failed or the reply was unreadable (a `wire_version` this worker does not know, after a one-sided deploy). | Deploy the endpoint and the worker from the same commit. Roll back with `MDX_DIAR_ENGINE=legacy`. |
| First job of the day is slow | `min_replica: 0` cold start (~4 min, inside the timeout). | Nothing. `keep-warm` if it becomes a complaint. |
| Diarization latency alert (p95 > 0.25 × audio) | Endpoint on CPU, or saturated at `max_replica`. | Check the endpoint's accelerator and replica count in the spec. |
| The endpoint refuses to start | `MDX_DIAR_SERVER_TOKEN` is empty, or `MDX_DIAR_DEVICE=cpu`. | Set the token (secret store, `docs/deploy/inventory.md`); anonymous is a laptop-only mode. CPU is refused on purpose (0.64–0.85 × audio — every recording would time out); `MDX_DIAR_ALLOW_CPU=1` overrides it deliberately. |
| Workers log `diarization.remote_unreachable` with `last_error='auth'` at startup | The worker's token is not the one the endpoint expects. | Compare `MDX_DIAR_SERVER_TOKEN` on both sides. This is the loud version of what used to be a silent week of speakerless transcripts. |

**Rollback** is still `MDX_DIAR_ENGINE=legacy` (in-process, no endpoint).
`MDX_DIAR_ENGINE=pyannote` is shape A and is the right setting the day a
worker has a GPU — the image still carries the weights.

The endpoint never receives a tenant id, job id, user, filename or any
text, stores nothing, and returns no embeddings. If a change would alter
any of that, it is an ADR, not a patch.

### § diarization-model-upgrade

Upgrading community-1 (or any baked diarization model): bump the revision in
`scripts/models/prepare_pyannote.py`, run `--resolve-pins` with a token whose
account accepted the model terms, commit the printed digests in the three places
PINS.md names, rebuild the image, then run it as `MDX_DIAR_SHADOW_ENGINE` first
(compare `mdx_asr_diarization_shadow_delta` and the gold set:
`make der-eval ENGINE=pyannote_c1`) before flipping `MDX_DIAR_ENGINE`. Old
transcripts are offered "Re-label with the current engine" once
`MDX_DIAR_CURRENT_ENGINE` (asr-service) names the new engine id — keep it equal
to the worker's engine.

### § rediarize (speaker re-labelling states)

`POST /asr/jobs/{id}/rediarize` recomputes speaker labels from the stored
audio and words — no ASR pass. The job's `status` stays `complete`; the
re-run has its own columns:

| `diarization_status` | Meaning |
| --- | --- |
| NULL | never re-labelled |
| `queued` | API accepted it and enqueued a `task=rediarize` message |
| `running` | a worker claimed it (conditional on `diarization_rev = target_rev − 1`) |
| `complete` | new artifact `{tenant}/{job}.r{rev}.json.enc`, row repointed, `diarization_rev` bumped |
| `failed` | `diarization_error` holds the kind; the job and its previous labels are untouched |

- **Deploy order: asr-worker BEFORE asr-service.** An old worker reads a
  rediarize message as a transcribe of a complete job and acks it — a
  silent no-op that leaves `diarization_status='queued'` until the reaper.
- Artifacts: the current one is `result_storage_uri`; exactly one previous
  one is kept (`previous_result_storage_uri`) for undo. Every read goes
  through `result_storage_uri`; never build the key from the job id.
- Sprint 28 merges carry the old `result_rev` and stop applying after a
  re-run or an undo (both bump `diarization_rev`). That is by design; the
  clients warn before confirming.
- Names follow a speaker when ≥ 60 % of its speech lands on one new label
  and no other named label lands there (`carry_over_mapping`).

### § rediarize-failures

`RediarizeFailureRateHigh`: > 10 % of re-runs failed in the last hour
(with ≥ 10 runs). Group by kind:

```sql
SELECT diarization_error, count(*) FROM transcription_jobs
WHERE diarization_status = 'failed' AND diarization_updated_at > now() - interval '1 hour'
GROUP BY 1 ORDER BY 2 DESC;
```

- `audio_missing` / `decrypt_failed`: storage or key problem — see
  § object-store-outage; the API only refuses erased audio up front.
- `diarization_unavailable` (retried, then `retry_exhausted`): the engine
  cannot load — § diarization-engine.
- `diarization_failed`: deterministic for that recording; not retried.
- `stranded`: the reaper failed a re-run left `queued`/`running` past the
  grace windows (a dead worker or lost message). Users can simply re-run;
  it does not count as an extra run beyond the one already spent.

### § stranded-rediarize

Same reaper and grace windows as § stranded-jobs
(`asr_tenants_with_stale_jobs` also returns tenants with stale
`diarization_status`, measured from `diarization_updated_at`). The reaper
fails only the re-run (`diarization_error='stranded'`), never the job.

### § diarization-slow

`DiarizationSlowVsAudio`: p95 of `mdx_asr_diarization_audio_ratio`
(diarization wall time ÷ audio duration, per job) above 0.25 for an hour.
Check `MDX_DIAR_DEVICE` (v2 on CPU is several times slower than on GPU),
`MDX_DIAR_V2_BATCH`, and whether a shadow engine is competing for the same
CPU (`MDX_DIAR_SHADOW_ENGINE` — turn it off first). Per job:
`metadata.diarization.seconds` against the job's audio duration.

### § dual-channel (mic + call audio captures, Sprint 31)

A macOS capture with `channel_layout=mic_system` is a 2-channel file:
ch0 = microphone, ch1 = call audio. The worker decodes it as int16 pairs
(`decode_to_pcm(channels=2)`, half the memory of float32), runs ASR ONCE on
the mixdown, and diarizes each side through the engine seam
(`diarization.dual_channel.diarize_dual`): a remote voice can never carry a
local label. `metadata.diarization.channel_layout` says what happened:
`mic_system` (per side), `mono_fallback` (see below) or `mono`.
The web app sends the same layout when "Also record this tab's audio (Me / Them)" is on (Sprint I3); iPhone recordings stay single-channel — iOS never declares `channel_layout`.

- Deploy order: asr-worker before asr-service. An old worker ignores the
  new payload fields and downmixes — safe, just without sides.
- Re-runs read the layout from `transcription_jobs.capture_context`.
- `leak_gain_db` / `local_speakers` / `remote_speakers` / `both_share` on
  the stats explain a result: a `leak_gain_db` of null means headphones.
- Automatic name: exactly one local speaker with ≥ 10 s of speech and a
  `local_speaker_name` on the submit → `speaker_names[label]` set with source
  `channel`. A person clearing it records `cleared`; it is never re-applied.
- Memory (measured, 2 h pink-noise stereo, M5): decode + mixdown peak
  1.9 GB, + Silero channel analysis 3.0 GB, before either engine pass. The
  full dual path on 2 h has NOT been measured yet against the 3.5 GiB
  budget.

### § dual-channel-fallback

`DualChannelMonoFallbackHigh`: > 5 % of dual-channel captures in 24 h were
diarized from the mixdown because the channel path raised. The user still
gets speakers. Look at `diarization.dual_fallback` log lines
(`error_class`, job id — no content). Typical causes: a malformed second
channel (a client writing garbage on ch1), Silero failing to load (the
channel analysis needs it even when the engine is pyannote), memory.

### § audit-chain-divergence (touching asr.*)

Same procedure as sprint-02 auth audit divergence; ASR kinds are
`asr.audio_uploaded`, `asr.job_queued`, `asr.transcription_*`,
`asr.job_cancelled`, `asr.speakers_*`, `asr.speaker_edit_reverted`,
`asr.rediarize_*`, `asr.audio_exported_for_eval`, `asr.quota_exceeded`.

### § speaker-correction-rate

`SpeakerCorrectionRateHigh`: of the diarized results opened in the last
7 days (≥ 50), more than 30 % got a correction — a first speaker edit or a
first re-run (`mdx_asr_speaker_corrected_jobs_total` ÷
`mdx_asr_diarized_results_opened_total`). Not an outage: a quality signal
for the weekly speaker review.

1. Speakers row: did it start with an engine switch or a threshold change
   (speakers per job by engine, shadow − primary delta)? If so, the switch
   is the suspect — § diarization-engine has the rollback.
2. Edit mix: mostly `merge` = over-count (split voices, § speaker-overcount);
   mostly `reassign` with created labels = under-count (merged voices);
   many re-runs = people use the hint to fix the count.
3. Break it down with the weekly cohort, which says where:
   `make weekly-speakers` → `speakers-YYYY-WW.csv`, rows by engine / hint /
   client / source / count_confidence (definitions and approximations:
   `docs/product/speaker-metrics.md`). Record what you find and decide in
   `docs/product/speaker-decisions.md`.
4. Nothing to do per job — people have already fixed their transcripts.
   Recordings that show a new failure pattern can join the eval set only
   with consent: `docs/runbooks/speakers-eval.md`.

### § prompt-echo (Sprint I2)

**Symptom.** A transcript contains names or role labels nobody said —
"Gysi, Moderator II, moderatorin, narrator, speaker background …" — at the
start of a passage, or for minutes on end; `AsrPromptEchoRate` fires.

**Cause.** Whisper is given the workspace glossary as its prompt. Over
audio it cannot decode (silence past the VAD, a breath, speech in another
language) it writes the prompt back, sometimes with real speech glued on.

**What the worker does now.** `asr_worker/echo.py` removes runs of ≥ 3
consecutive prompt words at a segment start or after a 1.5 s pause,
whatever backend decoded them; a segment left empty is dropped; the spans
are in the job's `diagnostics.prompt_echo` (timestamps and counts) and
in `mdx_asr_prompt_echo_words_total`. The old whole-segment rule
(`_is_prompt_echo`, needs `no_speech_prob ≥ 0.5`) still applies.

**If it fires.**
1. `scripts/admin/glossary_audit.py` — which workspaces still hold role
   labels (they are no longer sent since I2, but a large hint of real names
   echoes too on a bad recording).
2. `MDX_ASR_CONDITION_PREV` is `true` by default (off makes conversation
   chunks lower-case run-ons — T7); for a workspace that echoes anyway,
   `false` stops one echo becoming the next chunk's context.
3. A backend change (`ASR_BACKEND`, model) — compare the counter per backend.
4. A person disputing a removal: `GET /asr/jobs/{id}` has the exact
   `vocabulary_hint` (migration 0061) and the result's `diagnostics` say
   where; the Transcript tab shows "n words removed as prompt echo at
   mm:ss". Re-running the job without a hint is the undo (rediarize
   pattern; a dedicated route is I3's).

### § other-language (Sprint I2)

A VAD chunk ≥ 2 s whose language identification is sure of another
supported language (en/de/uk; p ≥ 0.6, and ≤ 0.2 for the recording's) is decoded in that
language, labelled `segment.language`, never translated (`task` is always
`transcribe`); counted in `mdx_asr_other_language_chunks_total`. In-process
engine only — an HTTP backend gives no per-chunk language, and the note
engine then falls back to its script heuristic. Turn it off with
`MDX_ASR_CHUNK_LANGUAGE_ID=false` if a bilingual workspace complains about
flips; report the chunk count first.

## Pre-flight after deployment

- Confirm `mdx_asr_model_loaded == 1` on every replica.
- Submit a known-good fixture via `scripts/dev/asr-smoke.sh` (1-line:
  POST a 5-second WAV; expect status=complete within 60 s).
- Confirm a non-zero `mdx_asr_warmup_seconds` exists per replica.
