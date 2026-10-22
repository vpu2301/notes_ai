# Telemetry schema v1

`telemetry_schema_version = 1`. Machine-readable: [`telemetry_v1.schema.json`](telemetry_v1.schema.json) (JSON Schema 2020-12).

## Conventions (repo-derived)

- **IDs:** UUID v4 (`uuid4()`), the repo-wide style (`audio_id`, `job_id`, `note_generations.id`, `jobs.id`). No ULIDs, no ints.
- **Tenant:** every entity carries `tenant_id` (RLS, like every tenant table since 0001). Not part of the spec's field list; required by the repo.
- **Missing ≠ zero.** A measurement not taken is `null`, and its reason sits in the entity's `null_reasons` map: `{"<field>": "unavailable|not_supported|not_measured|error|not_applicable"}`. Inside `attributes`, the same map is the reserved key `_reasons`. Validation rule: every nullable measurement that is `null` must have a `null_reasons` entry; a field with a value must not.
- **Observed vs configured:** device-like facts are `{"value": "<str>", "observation": "observed|configured"}`; a `configured` value is never promoted to `observed` by inference from a backend name.
- **Time:** wall timestamps are UTC ISO-8601 with milliseconds (`2026-10-22T09:12:03.123Z`); durations in seconds as floats; monotonic instants in integer nanoseconds (`time.monotonic_ns()`), meaningful only within one `process_id` + `host`.
- **Timing glossary** (overview, copied verbatim into code docstrings): `processing_wall_seconds`, `user_wait_seconds`, `time_to_transcript_seconds`, `time_to_speaker_labels_seconds`, `time_to_notes_seconds`, `rtf` (= processing_wall / audio, lower is better), `speedup` (= audio / processing_wall), `asr_audio_processed_seconds` (a **sum**, labelled as such). Note: today's `transcription_jobs.quality.rtf` is infer/audio and `mdx_asr_realtime_factor` is audio/infer — telemetry uses only the glossary definitions and never copies either.
- **Privacy:** no audio, transcript text, prompts, note content, credentials, participant names, user-name paths, raw bodies. Lengths, counts and hashes only. Enforced by `redact()` at the storage boundary (STORAGE.md §5).

## Entities

### `processing_run`

| Field | Type | Notes |
|---|---|---|
| `processing_run_id` | uuid | PK, minted at submission (CORRELATION.md) |
| `tenant_id` | uuid | |
| `recording_id` | uuid | = `transcription_jobs.id` |
| `note_id` | uuid? | set once a note is linked (`attach_transcript` / `from-transcript`) |
| `note_generation_id` | uuid? | the `note_generations.id` this run produced |
| `kind` | `initial\|reprocess` | |
| `reprocess_scope` | `diarization\|notes\|null` | which part a reprocess redoes (rediarize, regenerate); null for initial |
| `trigger` | `auto\|user\|retry\|migration` | |
| `telemetry_schema_version` | int | 1 |
| `attempts` | int | worker pickups of the run; a queue redelivery reuses the run and adds one (Sprint 2 §11) |
| `status` | `queued\|running\|succeeded\|failed\|cancelled\|partial` | |
| `error_category` | `input\|upload\|queue\|model_load\|asr\|diarization\|postprocess\|llm\|storage\|client\|unknown` \| null | |
| `submitted_at` | ts | server accepted the job |
| `started_at`, `finished_at` | ts? | first backend span start / final backend result stored |
| `processing_wall_seconds` | float? | derived, critical-path rule (CORRELATION.md §7) |
| `user_wait_seconds` | float? | needs client events |
| `time_to_transcript_seconds`, `time_to_speaker_labels_seconds`, `time_to_notes_seconds` | float? | needs client `*_displayed` events |
| `rtf`, `speedup` | float? | derived |
| `audio_duration_seconds` | float? | from `UploadFacts.duration_ms` |
| `asr_audio_processed_seconds` | float? | Σ primary + recovery audio fed to ASR |
| `created_by` | uuid? | identity `sub` of the submitter (an ID, not a name) |
| `concurrent_runs_at_start` | int? | runs in `running` state on the same worker host when this one started |
| `other_model_activity` | list | `[{kind: asr\|diarization\|llm, backend, run_id?, overlap_seconds}]` known concurrent activity |
| `telemetry_overhead_seconds` | float? | null + `not_measured` until Sprint 5 |
| `telemetry_buffer_peak_bytes` | int? | peak serialised size of the run's records in the write buffer (RSS proxy, Sprint 1 §6) |
| `retention_until` | ts | |
| `trace_id` | str? | W3C trace id when a trace exists |
| `null_reasons` | map | |

### `run_context` (1 per run, written at worker start; `_end` fields at finish)

| Field | Type |
|---|---|
| `processing_run_id`, `tenant_id`, `telemetry_schema_version` | |
| `app_commit`, `app_build` | str? (`BUILD_SHA` / image tag) |
| `os_name`, `os_version`, `arch`, `chip_model` | str? |
| `memory_total_bytes` | int? |
| `execution_mode` | `native\|container\|remote` |
| `effective_config` | object — redacted: model names, revisions, quantization, compute types, beam size, thresholds; no secrets, no user-name paths |
| `device_asr`, `device_diarization`, `device_llm` | device object |
| `memory_pressure_start/end` | str? (`normal\|warn\|critical`, macOS) |
| `process_rss_start/end`, `swap_used_start/end`, `container_mem_limit` | int? bytes |
| `null_reasons` | map |

One run spans several processes (asr-service, asr-worker, note-worker): `run_context` describes the **asr-worker** host; each span also carries `process_id` + `host`, and an optional per-process context lives in `span.attributes.process_context` for the first span of a process.

### `span` (tree, many per run)

| Field | Type |
|---|---|
| `span_id` | uuid |
| `processing_run_id`, `tenant_id` | uuid |
| `parent_span_id` | uuid? |
| `stage` | enum below |
| `name` | str (code-level name, e.g. `asr.transcribe_runs`) |
| `attempt` | int ≥ 1 |
| `status` | `ok\|error\|cancelled\|skipped\|partial` (+ `started` for the begin row of a long span) |
| `error_category` | enum? |
| `error_class` | str? — exception class name only |
| `start_monotonic_ns`, `end_monotonic_ns` | int? |
| `start_wall_utc`, `end_wall_utc` | ts? |
| `clock_source` | `monotonic\|wall\|client_wall` |
| `process_id` | int |
| `host` | str (hostname / container id, no user name) |
| `attributes` | object — stage-specific (below), `_reasons` map |
| `is_parallel_with` | uuid[]? |

Stage enum: `capture_input, upload, queue, model_init, audio_prep, vad, language_detection, asr_primary, asr_recovery, diarization_load, diarization_infer, postprocess_align, postprocess_attribute, postprocess_cleanup, persist, llm_call, ui_delivery, other`.

Mapping of today's code to stages: guards + prompt-echo + segment-LID re-decode + noise markers → `postprocess_cleanup`; `_apply_diarization` / `_split_segment_by_speaker` → `postprocess_attribute`; `clips_as_turns` / channel naming → `postprocess_align`; coverage second pass + loop re-decode → `asr_recovery`; shadow ASR → `other` (`name=asr.shadow`); asr-service read-time NLP enrichment + entity unify → `other` (`name=asr.result_enrich`), outside the critical path.

### `llm_call` (many per run; each also a `span` with `stage=llm_call`)

| Field | Type |
|---|---|
| `llm_call_id` | uuid |
| `span_id`, `processing_run_id`, `tenant_id` | uuid |
| `purpose` | `note_write\|note_merge\|note_check\|note_ask\|provider_probe\|inline_completion` (from PIPELINE_MAP §5) |
| `provider` | str (`openai_compat`, `llamacpp`, `ollama`) |
| `model` | str (response model id when present, else configured; `null_reasons` says which) |
| `backend` | str (registry name: `mistral_eu`, `dev_mac`, …) |
| `execution_mode` | `native\|container\|remote` |
| `streaming` | bool (always false today) |
| `attempt` | int |
| `status` | span status |
| `queue_wait_seconds` | float? — semaphore + 429 waits |
| `model_load_seconds` | float? — `warming` time |
| `time_to_first_token_seconds` | float? — `not_supported` while non-streaming |
| `total_latency_seconds` | float? |
| `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_tokens` | int? |
| `token_source` | `provider\|estimated` |
| `token_accounting_note` | str? (e.g. "OpenAI-compatible: completion_tokens includes reasoning_tokens") |
| `generation_tokens_per_second` | float? |
| `prompt_chars`, `completion_chars` | int? |
| `error_category` | enum? |
| `null_reasons` | map |

### `client_event` (many per run)

| Field | Type |
|---|---|
| `event_id` | uuid (client-minted, idempotency key) |
| `processing_run_id` | uuid? (resolved server-side when the client sends only `recording_id`) |
| `recording_id`, `tenant_id` | uuid |
| `client` | `web\|macos\|ios` |
| `client_version` | str |
| `event` | `recording_stopped\|import_submitted\|upload_started\|upload_finished\|transcript_displayed\|speaker_labels_displayed\|notes_displayed\|error_shown` |
| `client_wall_utc` | ts |
| `client_monotonic_ns` | int? |
| `server_received_utc` | ts |
| `estimated_clock_offset_ms` | int (`server_received_utc − client_wall_utc`, stored, never applied retroactively) |
| `attributes` | object, no content (`_reasons` map) |

Pre-submission events (`recording_stopped`, `import_submitted`, `upload_started`) happen before a `recording_id` exists: the client buffers them and sends them after `POST /asr/jobs` returns the job id (CORRELATION.md §4).

## Stage `attributes` (required keys; each nullable with `_reasons`)

| Stage | Keys | Source today |
|---|---|---|
| capture_input | `audio_duration_seconds, format, sample_rate_hz, channels, file_size_bytes, capture_mode` | server `UploadFacts` (duration, rate, channels, size, codec); `capture_context.source` + `channel_layout` → `capture_mode` |
| upload | `bytes, chunks, retries, resumed` | chunks = 1, resumed = false (no chunking); retries from client events |
| queue | `enqueued_at, started_at, queue_wait_seconds, queue_name, queue_depth_at_enqueue` | `asr:jobs` (XLEN at enqueue), `jobs` table for `note.generate` |
| model_init | `model_kind (asr\|diarization\|vad\|lang\|llm), model_name, model_revision, quantization, compute_type, device{value,observation}, state (cold\|warm), load_seconds, warmup_seconds` | `WhisperEngine.load`, `warm_up`, lazy diarizer/VAD/LID loads |
| audio_prep | `retrieve_seconds, decrypt_seconds, decode_seconds, resample_seconds, source_sample_rate_hz, target_sample_rate_hz` | fetch+decrypt are one call (`audio_store.get`) → `decrypt_seconds` null `not_supported`, `retrieve_seconds` covers both; ffmpeg decodes and resamples in one pass → `resample_seconds` null `not_supported` |
| vad | `backend, duration_seconds, speech_seconds, run_count, run_lengths_seconds, threshold` | `vad.speech_runs` |
| language_detection | `model, call_count, duration_seconds, detected [{lang, confidence}], decided_language` | `chunks.plan` |
| asr_primary | `backend, model, device{..}, compute_type, beam_size, wall_seconds, audio_processed_seconds, chunk_count, chunk_seconds, word_count, segment_count` | `transcribe_runs` |
| asr_recovery | `trigger_reason, attempt, audio_reprocessed_seconds, wall_seconds, recovered_words, backend, model, device{..}` | `_covered`, loop re-decode |
| diarization_load / diarization_infer | `backend, model, device{..}, load_seconds / infer_seconds, speakers_detected, unknown_speaker_share, audio_seconds` | `ensure_loaded`, `_diarize_capture` |
| postprocess_* / persist | `duration_seconds, items` | |
| ui_delivery | `client, event, seconds_since_submission` | derived from client events |
| llm_call | (fields live in `llm_call`) | |

`chunk_seconds` and `run_lengths_seconds` are lists; capped at 500 entries, overflow counted in `_truncated`.
