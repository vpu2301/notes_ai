# Pipeline map (Sprint 0 discovery, 2026-10-22)

Base: `cleaning-branch` (dictation-service and autocomplete-service removed). Paths are repo-relative.
"Logs/measures" = what exists today; "—" = nothing.

## 1. Capture / input

| Client | Stop | Import | Known at that moment |
|---|---|---|---|
| web | `web/src/lib/useRecorder.ts:218` `stop()` → `rec.onstop` :184 → `onDone(RecordedAudio)`; page `web/src/pages/MeetingPage.tsx:224` `onStop` → `submit()` :154 | `MeetingPage.tsx:239` `onFile` (`capture_source=upload`, mono, no timing) | `blob`, `filename`, `channelLayout` (`mono`/`mic_system`), `recordPressedAt` (ISO, `Date.now()` before mic prompt), `firstFrameOffsetMs` (clamped 0..600 000); mime from `pickMimeType()` :25 (webm/opus, webm, mp4). **Not known/sent:** duration (only UI `elapsedMs`), sample rate, file size |
| macOS | `CaptureViewModel.finishRecording()` `macos/Sources/NotesAICapture/CaptureViewModel.swift:305` → `process` :326; recorder `Recorder.swift:313` `stop()` | `AppState.swift:959` NSOpenPanel → `CaptureViewModel.upload(fileURL:)` :264 | FLAC 16 kHz (WAV fallback), 1 or 2 channels; `CaptureMode` `.micAndSystem`/`.micOnly(reason)` (`Recorder.swift:81`); `CaptureTiming(pressedAt, firstFrameAt)` :308; `recorder.elapsed`. **Not computed:** file size, imported-file sample rate |
| iOS | `CaptureViewModel.finishRecording()` `ios/Sources/NotesAICapture/CaptureViewModel.swift:255` → `process` :283 | `Views/HomeView.swift:152` `.fileImporter` → `uploadFile(_:)` `CaptureViewModel.swift:166` | mono FLAC 16 kHz (WAV fallback); no system audio; `captureTiming` `Recorder.swift:173` |
| shared | `clients/Shared/CaptureContext.swift:6` (`speakersMax`, `nameCandidates`, `source` = `calendar_event|manual|upload`), `CaptureCoverage.swift:9` `CaptureTiming` | | |

**Server is the only place duration/sample rate are measured:** `probe_audio` → `UploadFacts` (`mime_type, size_bytes, duration_ms, sample_rate_hz, channels, codec, sha256`) in `services/asr-service/src/asr_service/validators/duration.py:24`, `validators/result.py:44`.
Logs/measures: audit `AUDIO_UPLOADED {size_bytes, duration_ms, sample_rate_hz, codec}` (no channels); `audio_files` row stores `mime_type, size_bytes, duration_ms, sha256` only.

## 2. Upload

| Side | Code | Notes |
|---|---|---|
| server | `POST /asr/jobs` → `submit_job` `services/asr-service/src/asr_service/routers/jobs.py:211-470` | single multipart, `await audio.read()` (whole file in memory, :265); limits `MD_ASR_MAX_UPLOAD_MB=250`, `MD_ASR_MAX_DURATION_SECONDS=7200` (`config.py:109-110`); per-tenant concurrency cap :281-297; `audio_id`, `job_id` = `uuid4()` :299-300; encrypted put `{tid}/{audio_id}.enc` (`libs/storage/.../object_store.py:61`, AES-GCM envelope, per-tenant KEK) before the DB insert |
| web | `submitJob()` `web/src/api/asr.ts:40`; `submitWithLayoutFallback()` :83 (one re-post as mono on `channel_layout_mismatch`) | no network retry, no pending queue; 401 → single-flight refresh + one retry (`http.ts`) |
| macOS | `APIClient.submitJob` `macos/.../APIClient.swift:1366` (whole file in memory, timeout 120 s :48); fields `jobFields` :1414 | on failure `keep()` → `PendingCaptures` (`PendingCaptures.swift:103`, sidecar JSON with timing/layout/tenant); `PendingUploads.retryAll/retry` (`PendingUploads.swift:74,85`); auto-retry only after sign-in/reconnect (`AppState.retryPendingUploads` :304) |
| iOS | `APIClient.submitJob` `ios/.../APIClient.swift:1369` (`ensureFreshToken`, can borrow a token for another tenant; no channel layout) | `keep` → `PendingCaptures`; `AppState.retryPending` :907 |

No chunking, no resumable upload, no Content-Range anywhere.
Logs/measures: `mdx_asr_uploads_total`, `mdx_asr_validation_failures_total`, `mdx_asr_jobs_total{status}`.

## 3. Queue

- ASR: **Redis Streams** (not libs/jobs). Stream `asr:jobs`, group `asr-workers`, DLQ `asr:jobs:dlq` (`services/asr-worker/src/asr_worker/config.py:231-235`). Producer `RedisStreamsProducer.send` (XADD, `libs/messaging/src/messaging/redis_streams.py:49`); enqueue site `jobs.py:372-396` (publish failure → `ENQUEUE_FAILED`, 503, client resubmits = new audio_id + job_id). Payload `JobEnqueuePayload` (`libs/asr_models/src/asr_models/job.py:29`).
- Worker: `asr_worker/main.py:20` → `build_state` (`main_deps.py:137`) → `run_forever` (`processor.py:192`) → `_process_one` (`processor.py:317`).
- Status on `transcription_jobs`: claim `status='running', started_at=now(), attempts+1` (`processor.py:356-363`, **every delivery overwrites `started_at`**); complete :558-589 (`result_storage_uri, finished_at, metadata, detected_language, quality, diarization_*`); failed `_mark_failed` :1807; cancelled `_mark_cancelled` :1787.
- Retry: `_classified` :310; retryable → `_fail_or_retry` :226, Redis delivery counter (`_bump_attempts`), `MD_ASR_JOBS_MAX_RETRIES=3` → DLQ + `RETRY_EXHAUSTED`; redelivery via XAUTOCLAIM after `MD_ASR_JOBS_IDLE_RECLAIM_MS=60000`. **No heartbeat** (a job running > 60 s can be reclaimed while alive — unverified duplicate-processing risk; idempotent skip at :345).
- Backstop reaper: asr-service `domain/reaper.py:169` `sweep_once`.
- Cancellation: `DELETE /asr/jobs/{id}` → `cancel_job` `jobs.py:1946` → `request_cancel` (`repository.py:258`); queued → `cancelled` at once, running → `cancel_requested=true`; worker checks :353/:404/:532, `_cancel_poller` :1740 (≤ 1/s) inside ASR, `_unless_cancelled` :1759 around diarization.
- Reprocess = **rediarize only**: `POST /asr/jobs/{id}/rediarize` (`jobs.py:1742`) → `claim_rediarize` (`repository.py:538`) → same stream, `task="rediarize"`; worker `_rediarize_one` (`processor.py:1404`); same job row, `diarization_rev+1`, new object `{tid}/{job_id}.r{rev}.json.enc`, `status` stays `complete`, `started_at/finished_at` untouched, only `diarization_updated_at`. No re-transcribe endpoint.
- Note generation: **libs/jobs Postgres queue** (`jobs` table, 0022), kind `note.generate`, `JobRunner` (`libs/jobs/src/jobs/runner.py:127`), fair claim `jobs_claim_fair` (0055), max_attempts 5, `warming` parks the job.

Logs/measures: `mdx_jobs_claimed_total{kind}`, `mdx_jobs_finished_total{kind,outcome}`, `mdx_jobs_processing_seconds`, `mdx_jobs_queued_age_seconds` (libs/jobs only; nothing for the ASR stream wait).

## 4. Worker stages (asr-worker, in order)

| # | Stage | Code | Measured today |
|---|---|---|---|
| 1 | model init (startup) | `build_asr` `main_deps.py:124`; `WhisperEngine.load` `inference.py:101-150` (faster-whisper `WhisperModel(device, compute_type)` + 5 s silence warm-up); HTTP backends `HTTPASRProvider.warm_up` `libs/models/.../asr_http.py:105` (probe clip) | logs `whisper.loading` (configured device/compute/repo/rev/sha), `whisper.loaded{warmup_seconds}`; gauges `mdx_asr_warmup_seconds`, `mdx_asr_model_loaded` |
| 1b | diarizer / VAD / LID load | `build_diarizer` `main_deps.py:60` (**not warmed; lazy `ensure_loaded` on first diarized job, untimed**); Silero lazy `vad._ensure_loaded` `vad.py:44` (stub fallback); LID whisper-tiny lazy `chunks._load_local_model` `chunks.py:123` | — |
| 2 | audio prep | fetch+decrypt `audio_store.get` `processor.py:378-390`; `_decode_capture` :1117 → `audio_io.decode_to_pcm` (`audio_io.py:17`, ffmpeg → 16 kHz f32/s16) | `mdx_asr_audio_duration_seconds`; **fetch/decrypt/decode untimed** |
| 3 | orchestration | `decode_recording` `processor.py:669`; budget `max(60, audio_s × MD_ASR_MAX_INFERENCE_SECONDS_MULTIPLIER)` :411-416 | — |
| 4 | VAD | `vad.speech_runs` `vad.py:175` (to_thread at `processor.py:689`), floor pass per channel | logs `vad.floor_pass`, `vad.no_speech`; untimed |
| 5 | language detection | `chunks.identifier_for` `chunks.py:201` (EngineLID inproc / BackendLID http); `chunks.plan` :226 | `Diagnostics.language_id`, `other_language_chunks`, counter; untimed |
| 6 | primary ASR | inproc `InProcASRProvider.transcribe_runs` (`asr_inproc.py:127`) → `WhisperEngine.transcribe_runs` (`inference.py:227-274`); http `HTTPASRProvider.transcribe_runs` (`asr_http.py:179-260`, `plan_groups`, `_transcribe_once` :287, warming retry :266) | `metadata.infer_seconds` (transcribe_runs only), `vad_seconds_speech` (speech length, not VAD time), `gpu_seconds` (= infer if configured device is cuda), `peak_gpu_mem_mb` (torch only), `beam_size`, `Diagnostics.segments`; `UsageRecord` per call → log only (no ledger in asr-worker) |
| 7 | guards | `guards.apply` (`guards.py:215`) | `Diagnostics.dropped_segments/artefact_kept/gate_unavailable/loop_ranges`, counters |
| 8 | prompt-echo guard | `_guarded` `processor.py:780` → `echo.guard_segments` (`echo.py:148`) | `Diagnostics.prompt_echo*`, counters |
| 9 | recovery (second pass) | `_covered` `processor.py:811-1026`; triggers `cov.second_pass_cause` (`coverage.py:92`: `low_coverage|prompt_echo|decoder_empty`), loop ranges (`LOOP_CAUSE`), deadline (`timeout`); needs `MD_ASR_SECOND_PASS_ENABLED` + real VAD | `Diagnostics.coverage`, `second_pass{chunks, recovered_words, by_cause}`, `loops`, `metadata.coverage_share`; `mdx_asr_second_pass_total{cause,outcome}`; **second-pass time untimed and not in infer_seconds** |
| 10 | segment LID re-decode | `segment_lid.rediscover` (`segment_lid.py:283`) when `MDX_ASR_SEGMENT_LID_ENABLED` | `Diagnostics.segment_language`, counters |
| 11 | noise markers | `chunks.nonspeech_regions` `chunks.py:362` | `output.noise` |
| 12 | shadow ASR (sampled) | `shadow.run` `shadow.py:93` (`MDX_ASR_SHADOW_BACKEND`, `_RATE`) | `Diagnostics.shadow` (own rtf) |
| 13 | ASR total | `processor.py:484-488` `infer_seconds = now − t0`, **t0 set at :374 before fetch** → covers fetch…segment LID | `mdx_asr_inference_seconds`, `mdx_asr_realtime_factor` (audio/infer), audit `TRANSCRIPTION_COMPLETE` |
| 14 | diarization load / infer | load `diarizer.ensure_loaded()` :496 (untimed); infer `_diarize_capture` :1137 (`diarize_dual` for mic_system, else `diarizer.diarize` in thread), timed :504-523 → `DiarizationStats.seconds`; engines legacy ECAPA (`libs/diarization/.../engine.py:34`), pyannote (`pyannote_engine.py:99`), HTTP (`http_engine.py:44`, server returns `seconds`) | `mdx_asr_diarization_seconds{engine}`, audio ratio, speakers, unknown_share, clusters_dropped, dual_jobs; remote failure → job completes with `diarization_status='failed'` |
| 15 | attribution / cleanup | `_apply_diarization` :1029 → `_split_segment_by_speaker` :1317, `clips_as_turns` :1263, `_channel_name` :1180 | — |
| 16 | persist | `transcript_store.put("{tid}/{job_id}.json.enc")` :545-556; row update :558-607 with `quality.summarize` (`quality.py:21`: `audio_s, speech_s, infer_s, rtf` — **rtf here = infer/audio, the metric uses audio/infer**); `emit_transcription_completed` (`notifications.py:16`) | `quality` jsonb |
| 17 | read-time (asr-service) | `entity_unify` / `corrections.plan_for` (`jobs.py:685, 818-850`, budget → `skipped_budget`); NLP enrichment `_enriched_result_view` `jobs.py:910` → nlp-service; `mark_result_read` → `result_first_read_at` | `mdx_asr_entity_unify_seconds`, `mdx_asr_result_enrichment_total` |

## 5. Note generation (LLM)

Trigger: **not server-side.** The client polls the ASR job, then `POST /notes/{note_id}/transcript` → `attach_transcript` (`services/note-service/src/note_service/routers/notes_meeting.py:489`) → `_fetch_transcript` (`routers/notes_from_transcript.py:98`, user's bearer) → `generation_service.start` (`domain/generation_service.py:62-134`): snapshot `{tid}/generation/{note_id}/{gen_id}.json`, `note_generations` row, `JobQueue.enqueue(kind="note.generate")` in one transaction. Other entries: `notes_from_transcript.py:405`, regenerate `notes_generation.py:530`.

Provider layer: `libs/models` `ChatProvider.complete` → `ProviderResult(text, json, input_tokens, output_tokens, latency_ms, backend, model_id, structured_mode, finish_reason)` (`protocols.py:17-49`). Every chat backend is `kind: openai_compat` (`openai_compat.py`): **no streaming** (`"stream": False` :236); read timeout per backend (dev_mac 900, mistral_eu 120, mistral_eu_small 60, hf_eu 300 s), connect 5 s; semaphore `max_concurrency` held across retries; retries `warming|unavailable|timeout` (3 attempts, 1 s/2 s; warming polls `Retry-After` within `cold_start_seconds`); 429 budget 120 s/call, 600 s/generation (`throttle.py`). **Usage parsed: only `prompt_tokens`, `completion_tokens`** (`_parse` :378-380); `total_tokens`, `cached_tokens`, `reasoning_tokens`, `id`, `system_fingerprint` dropped; `latency_ms` = monotonic across all attempts; no TTFT, no queue wait. Selection: `Registry.resolve(workspace_id, operation)` (`registry.py:306`) → workspace settings (0053) → env overrides → `routing[op][tier]`; dev `chat = {primary: mistral_eu, fallback: dev_mac}`.

| Purpose | Call site | Selection / mode | Exposes |
|---|---|---|---|
| `note_write` (per 25-min window) | `writer.write` `services/note-service/src/note_service/domain/writer.py:249`, call :285 | `registry.resolve(tenant,"write")` via `_Providers.get` (`worker.py:67`); free text; `max_tokens` workspace (4096) | `Written.stats`: model, backend, windows, calls, tokens_in/out, latency_ms (Σ), wall_ms, words, … |
| `note_merge` (> 1 window) | `writer.py:310-330` (`MERGE_RETRIES=1`, then `merge_failed_text`) | same provider | in `Written.stats` |
| `note_check` (`MDX_NOTE_CHECK`, default off) | `checker.check` `domain/checker.py:80`, call :103 | JSON schema, 1500 tokens, T=0 | items, unsupported, calls, failed_calls, tokens; **no latency** |
| `note_ask` | `NoteAsker.answer` `domain/ask.py:135`, call :160; route `POST /v1/notes/{id}/ask` (`routers/notes_ask.py:120`) | `resolve(ws,"ask")`, 700 tokens, T=0.2 | backend, model_id, tokens, latency_ms; audit `NOTE_ASKED` |
| `provider_probe` (before every note job, 1–2 real completions) | `worker.py:141-143` → `provider.probe()` (`openai_compat.py:88`) | | — |
| `inline_completion` (generation-service, Layer C) | `routers/completions.py:94`; own adapters `adapters/inference.py` (`LlamaCppClient` :40, `OllamaClient` :70) — **not libs/models** | `MDX_GEN_BACKEND`, `MDX_GEN_MODEL` (gemma3:1b), 600 ms budget, 24 tokens, no retry | `CompletionResult(text, model)`; provider timings/token counts discarded; not in `model_usage` |

Titles, summaries and action items are **not** separate LLM calls — parsed from the writer's Markdown. Field extraction, punctuation, entity unify, speaker name suggestions, glossary: **no LLM** (rule-based / local token-classifier).
Job-level retry: `JobRunner` (warming parks; other errors retry up to 5). Ledger: `model_usage` (0023) via `UsageLedger` (`libs/jobs/src/jobs/ledger.py:32`), installed only in note-worker + ask path; `workspace_id` never set; cost table loaded from `config/models.yaml` (rates live in `config/model_costs.yaml` per docstring → costs come out 0).

## 6. Result delivery

All polling; no push (no APNs), no client WebSocket (notification-service WS `/ws/notifications` exists, no client connects).

| Client | Transcript ready | Notes ready | First render: transcript / speaker labels / notes |
|---|---|---|---|
| web | `useCaptures` `web/src/lib/useCaptures.ts:9` (3 s) → auto `createFromTranscript`/`attachTranscript` → navigate `/notes/:id` | `GenerationStatus` `web/src/components/GenerationStatus.tsx:10` (2 s) → reload | `NoteEditorPage.tsx`: `TranscriptView` :649 (load `getResult` :711, mounted :2369, tab `transcript`) / `<SpeakerRoster>` :1121 + `turnName` :371 / `<SectionField generated>` :2452,:2458 (tab `notes`) |
| macOS | `CaptureViewModel.process` loop 3 s (`CaptureViewModel.swift:364-380`) → `phase=.done` | `NoteViewModel.followGeneration()` `NoteViewModel.swift:404` (2 s) | `Views/NoteView.swift`: `transcript` :906 (`loadTranscript` :1029) / `SpeakerRosterView` :936 / `sections` :609 |
| iOS | `CaptureViewModel.follow(_:)` :331 (3 s) | `NoteViewModel.swift:129` (2 s) | `Views/NoteView.swift`: `transcript` :861 / `SpeakerRosterView` :902 / `sections` :562 |

Speaker relabel polling: web `SpeakerRoster.useRelabel` (3 s), macOS rediarize poll ≈ `NoteViewModel.swift:955`.

## 7. Existing observability

- **Metrics:** OTel meters → OTLP → collector → Prometheus `:8889` (`add_metric_suffixes: false`, `infra/otel/otel-collector-config.yaml`); scrape config only prometheus + collector. Full inventory per service in the Sprint 0 agent notes; relevant here: asr-worker `mdx_asr_inference_seconds`, `_audio_duration_seconds`, `_realtime_factor`, `_gpu_memory_peak_mb`, `_warmup_seconds`, `_model_loaded`, `_diarization_seconds{engine}`, `_second_pass_total{cause,outcome}`, `_coverage_share`; libs/jobs `mdx_jobs_*`, `mdx_model_calls_total{backend,operation,outcome}`, `mdx_model_latency_seconds{backend,operation}`, `mdx_model_cold_starts_total`, `mdx_model_cost_cents_total{backend,tier}`; note-service `mdx_note_generations_total{outcome,backend,instructed}`, `mdx_note_generation_seconds_histogram` (**declared, never recorded**). No token metrics.
- **High-cardinality labels today:** `tenant_id` on `mdx_audit_writes_total`, `mdx_audit_write_retries_total` (`libs/audit/src/audit/writer.py:84,96`), `mdx_auth_refresh_replay_total` (`login.py:355`, `session_native.py:216`). No job/note/user IDs on metrics.
- **Histogram view bug:** `setup_metrics` (`libs/observability/src/observability/metrics.py:57`) applies ms buckets to every `*latency*` instrument, including `mdx_model_latency_seconds` (seconds).
- **Tracing:** TracerProvider + OTLP + W3C propagator (`libs/observability/src/observability/tracing.py:31`), auto-instrumented asyncpg + httpx; FastAPI instrumentation in each service `main.py`; workers bootstrap without it. **No manual spans anywhere.** traceparent rides httpx implicitly; **not propagated** through `jobs.payload` or Redis Streams. Jaeger :16686.
- **Logging:** JSON (`libs/observability/.../logging.py:25`), `trace_id/span_id` via `CorrelationIdFilter`, `PIISafeFilter`; `X-Request-ID` set by middleware but not logged or forwarded.
- **Error tracker:** none (no Sentry).
- **Timing in DB rows:** `transcription_jobs` (`queued_at, started_at, finished_at, attempts, metadata, quality, record_pressed_at, first_frame_offset_ms, diarization_updated_at, result_first_read_at`), `note_generations` (`created_at, finished_at, stats`; no `started_at`), `jobs` (`run_at, started_at, finished_at, heartbeat_at, attempts, waiting_*`), `model_usage`, `audit.events`.
- Dashboards: asr-health, auth-audit, layer-c-replay-search, meeting-quality, nlp-health, notes, template-service, templates, viral-loop, workspaces (Grafana :3000, admin/admin dev).

## 8. Backends and devices

- Registry `config/models.yaml` + `libs/models/src/models/registry.py` (`ENV` gates `enabled_in_envs`). ASR backends: `inproc_cpu_asr` (faster-whisper/CTranslate2), `dev_mac_asr` (whisper.cpp `whisper-server`, Metal, `host.docker.internal:8080`), `dev_mac_parakeet_asr` (:8082, NeMo/onnx_asr in `deploy/asr-server`), `hf_eu_asr`, `cand_*`. Diarization: `MDX_DIAR_ENGINE=legacy|pyannote|http` (default legacy ECAPA via speechbrain + Silero), `dev_mac_diar` (:8081, `deploy/diar-server`), `hf_eu_diar`.
- Env: `ASR_BACKEND` (default `inproc_cpu_asr`), `MD_ASR_DEVICE` (default cuda; compose cpu), `MD_ASR_COMPUTE_TYPE` (float16; compose int8), `MD_ASR_MODEL`, `MDX_DIAR_DEVICE` (cpu), `MDX_ASR_LID_MODEL`.
- **Observed device: nowhere.** All logs report configured values. Only runtime checks: `torch.cuda.is_available()` (peak memory, cache release). No `ctranslate2.get_cuda_device_count/get_supported_compute_types`; whisper-server/diar-server/asr-server `/health` report no device. `torch.backends.mps` only in `scripts/eval/engines/pyannote_c1.py:46`; `ollama ps` "100% GPU" only in `scripts/dev/dev-model.sh:224-231`.

## 9. Auth & admin

- `MDX_IDP_MODE` = `keycloak|dual|native` (`services/auth-service/src/auth_service/config.py:53`); dev compose `dual`; e2e `native`; prod k8s `keycloak`. Native: RS256 JWT, `iss=AUTH_ISSUER_URL`, aud `mdx-api`, access 900 s; refresh `nrt_` prefix, web cookie `mdx_rt` (HttpOnly), access token in memory.
- Roles: tenant membership `owner|admin|member|assistant|viewer|guest` (`routers/tenants.py:50`) → JWT platform roles (`identity_repository.py:50`): owner/admin → `[tenant_admin, member]`, member/assistant → `[member]`, viewer, guest. Matrix `libs/auth/src/auth/perms.py:14-60`. **No platform-wide super-admin / operator role.**
- Admin today: auth-service `/admin/users/*` (`routers/admin.py:34`, `requires("user.*")` + MFA); note-service `/v1/admin/sharing/{stats,policy,revoke-all}` (`routers/sharing_stats.py:22`); web `/admin/sharing` (`web/src/App.tsx:188`, sidebar for owner/admin `AppShell.tsx:965-967`). `/admin/dashboard` is free (catch-all `*` → `/` at `App.tsx:208`).
- Password login takes an **`EmailStr`** (`routers/password.py:58`) — a bare `admin` is not a valid login identifier today.
- Dev users: `scripts/seed/seed.sql:18-26` (admin@/owner@/member@/viewer@/auditor@tenant-a.example, member@/admin@tenant-b.example, vpu2301@gmail.com), Keycloak realm `infra/keycloak/realm-export.json` (dev-admin, dev-owner, … password `dev-password`). Grafana admin/admin.
- Environment marker: **`ENVIRONMENT`** (default `development`; `production`/`staging` = prod) in every service config. `ENV` = models registry env (dev/test/staging/prod). No `APP_ENV`/`MDX_ENV`.

## 10. Storage

Postgres 16, raw SQL migrations `infra/postgres/migrations/NNNN_*.sql` + `.down.sql` (latest **0091**), runner `scripts/db/migrate.py` (`make migrate-up|migrate-down|migrate-status`), asyncpg (no ORM). New tables need RLS policies + `GRANT … TO app_role` (`check-rls`), and any column referencing `notes(id)` or `transcription_jobs(id)` must be in `move_note_to_workspace` or `LEFT_ALONE` (`scripts/ci/check-note-move-covers-all-tables.py`).

| Table | PK | Relevant |
|---|---|---|
| `audio_files` (0004) | `id` uuid | mime, size, duration_ms, sha256; 1:1 with a job |
| `transcription_jobs` (0005+) | `id` uuid | `audio_id` FK; capture_context, record_pressed_at, first_frame_offset_ms, queued/started/finished_at, attempts, metadata, quality, diarization_rev |
| `notes` (0009) | `id` uuid | `source_asr_job_id` |
| `note_meetings` (0049) | `note_id` | `client_capture_id` (client-minted at record press, unique per tenant), `asr_job_id`, `started_at` |
| `note_generations` (0052) | `id` uuid | `job_id`, `transcript_rev`, `stats`, created/finished_at |
| `jobs` (0022) | `id` uuid | libs/jobs queue |
| `model_usage` (0023) | `id` uuid | per model call |

**No `recordings` table.** One upload = one `audio_files` row = one `transcription_jobs` row; every later artefact (note, meeting, edits, rediarize revisions, regenerations) references `transcription_jobs.id`. → `recording_id := transcription_jobs.id` (see CORRELATION.md).

## 11. Deployment shapes

- Dev: `make dev-up` = `docker compose up -d --build` (base + auto-merged `docker-compose.override.yml`): postgres, redis, minio, kafka, keycloak :8088, otel, jaeger, prometheus :9090, grafana :3000, loki; services auth :8000, asr :8001, notification :8004, nlp :8005, note :8006, generation :8009; asr-worker (CPU faster-whisper large-v3 int8 from host HF cache), note-worker, llama-server :8089, mailpit.
- Native on the Mac (`make dev-model`, `scripts/dev/dev-model.sh`): Ollama :11434, whisper-server (Metal) :8080 (or :8090), parakeet :8082, diar-server :8081 — reached from containers via `host.docker.internal`. The asr-worker itself always runs in Docker; no native asr-worker target (UNKNOWN whether one is wanted).
- GPU: `infra/compose/gpu.yml` (CUDA 12.4). Prod: Helm `infra/k8s/notes`.
- **Runtime detection: none today.** Candidates: `/.dockerenv`, `/proc/1/cgroup` / `/proc/self/mountinfo`, cgroup v2 `memory.max`, `KUBERNETES_SERVICE_HOST`.

## 12. Test & dev tooling

- Backend: `make dev-up && make migrate-up && make seed`; `make smoke`, `make smoke-notes`, `make test`, `make chaos-asr`; never DB integration suites against dev (they wipe it).
- Web: `cd web && npm run dev` → **port 5173** (`strictPort`, `web/vite.config.ts`); no proxy, bases `VITE_AUTH_BASE` :8000, `VITE_ASR_BASE` :8001, `VITE_NOTIFICATION_BASE` :8004, `VITE_NOTE_BASE` :8006 (`web/src/api/http.ts:16-21`). → dashboard at `http://localhost:5173/admin/dashboard`.
- Fake recordings: `scripts/smoke/ios_signup_e2e.py` `one_second_of_audio()` (440 Hz WAV, `--seconds`); `libs/models/src/models/probe_clip.wav` (2.77 s); `scripts/eval/make_tts_fixture.sh` (macOS `say` → `tests/fixtures/eval/audio/10min_de.wav`, gitignored); synthetic meetings `tests/fixtures/eval/meetings/m01..m05`.
- UNKNOWN: contents of `web/tests/fixtures`; audio fixtures in the macOS/iOS test targets.
