# Diagnostics — recording 19649657-4856-482f-8399-b078988a9fd0

Run `a159843f-f45b-4d84-a176-21f75c8fd2ea` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 19649657-4856-482f-8399-b078988a9fd0 |
| processing_run_id | a159843f-f45b-4d84-a176-21f75c8fd2ea |
| kind | initial |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | ce7f25a |
| app build | — (unavailable) |

### Hardware & environment

| Field | Value |
|---|---|
| OS | Linux 7.0.14-linuxkit |
| arch | aarch64 |
| chip | — (not_supported) |
| memory | 14,636,097,536 B (13.63 GiB) |
| execution mode | container |
| container limit | — (unavailable) |

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| asr | inproc_cpu_asr | /opt/models/whisper-large-v3/snapshots/edaa852ec7e145841d8ffdb056a99866b5f0a478 | edaa852ec7e145841d8ffdb056a99866b5f0a478 | int8 | int8 | cpu | observed |
| diarization | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | — | — | — | cpu | configured |
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 113.84 s |
| processing_wall_seconds | 209.41 s |
| rtf | 1.839 |
| speedup | 0.544 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.11 s | 0.1 % | -0.11 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.10 s |
| other | worker_job | 1 | ok | 203.24 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.13 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| vad | · vad.speech_runs | 1 | ok | 2.02 s | 1.0 % | +0.15 s |
| language_detection | · lid.recording | 1 | ok | 6.01 s | 2.9 % | +2.17 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 2.5 % | +8.18 s |
| language_detection | · lid.run | 1 | ok | 5.38 s | 2.6 % | +13.48 s |
| language_detection | · lid.run | 1 | ok | 5.45 s | 2.6 % | +18.86 s |
| language_detection | · lid.run | 1 | ok | 5.24 s | 2.5 % | +24.32 s |
| language_detection | · lid.run | 1 | ok | 5.32 s | 2.5 % | +29.56 s |
| language_detection | · lid.run | 1 | ok | 5.16 s | 2.5 % | +34.89 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 2.5 % | +40.05 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 2.5 % | +45.32 s |
| language_detection | · lid.run | 1 | ok | 5.17 s | 2.5 % | +50.61 s |
| language_detection | · lid.run | 1 | ok | 5.35 s | 2.6 % | +55.78 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 2.5 % | +61.14 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 2.4 % | +66.39 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 2.6 % | +71.42 s |
| language_detection | · lid.run | 1 | ok | 5.82 s | 2.8 % | +76.88 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 113.29 s | 54.1 % | +82.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.09 s | 3.9 % | +82.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.85 s | 3.7 % | +90.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 3.9 % | +98.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.03 s | 3.8 % | +106.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.35 s | 4.0 % | +114.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.24 s | 3.9 % | +123.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.73 s | 4.2 % | +131.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.49 s | 3.6 % | +140.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.82 s | 3.7 % | +147.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.31 s | 3.5 % | +155.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.01 s | 5.3 % | +162.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.47 s | 4.0 % | +173.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.26 s | 3.5 % | +182.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.43 s | 3.1 % | +189.56 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +195.99 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +195.99 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +196.00 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +196.00 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.22 s | 3.4 % | +196.00 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +203.22 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +203.22 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +203.22 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +203.26 s |
| queue | · asr.queue_wait | 1 | ok | 203.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +203.27 s |
| queue | · asr.queue_wait | 1 | ok | 203.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +203.27 s |
| queue | · asr.queue_wait | 1 | ok | 203.26 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 1.03 s | 0.5 % | +203.77 s |
| other | notes.generate | 1 | ok | 4.61 s | — | +204.80 s |
| llm_call | · llm.note_write | 1 | ok | 4.52 s | 2.2 % | +204.85 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 100.83 s | 14 | 2.83 s | 6.81 s | 17.12 s |

### Language checks

Language checks: 15.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 6.01 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 5.29 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 5.38 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 5.45 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 5.24 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 5.32 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 5.16 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 5.27 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 5.29 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 5.17 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 5.35 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 5.25 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 5.03 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 5.46 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 5.82 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 8.09 s | 1.259 |
| asr.chunk | faster_whisper | 7.23 s | 7.85 s | 1.086 |
| asr.chunk | faster_whisper | 6.88 s | 8.16 s | 1.186 |
| asr.chunk | faster_whisper | 6.75 s | 8.03 s | 1.190 |
| asr.chunk | faster_whisper | 7.26 s | 8.35 s | 1.150 |
| asr.chunk | faster_whisper | 7.93 s | 8.24 s | 1.039 |
| asr.chunk | faster_whisper | 8.86 s | 8.73 s | 0.986 |
| asr.chunk | faster_whisper | 5.31 s | 7.49 s | 1.412 |
| asr.chunk | faster_whisper | 5.34 s | 7.82 s | 1.465 |
| asr.chunk | faster_whisper | 5.79 s | 7.31 s | 1.263 |
| asr.chunk | faster_whisper | 17.12 s | 11.01 s | 0.643 |
| asr.chunk | faster_whisper | 8.38 s | 8.47 s | 1.011 |
| asr.chunk | faster_whisper | 4.73 s | 7.26 s | 1.534 |
| asr.chunk | faster_whisper | 2.83 s | 6.43 s | 2.267 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 100.83 s |
| audio duration | 113.84 s |
| reprocessing ratio | 0.886 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 7.22 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.02 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.52 s | 1,764 | 0 | 0 | 308 | — (not_supported) |
| **total** |  | 2 |  |  | 5.54 s | 1,776 | 0 | 0 | 314 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,394,947,584 B (2.23 GiB) → 3,103,670,272 B (2.89 GiB) |
| swap used | 50,384,896 B (0.05 GiB) → 50,294,784 B (0.05 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,599 B |

### Missing measurements

- **audio_prep**
  - asr.audio_prep: `decrypt_seconds` (not_supported)
  - asr.audio_prep: `resample_seconds` (not_supported)
  - asr.audio_prep: `source_sample_rate_hz` (unavailable)
- **capture_input**
  - asr.submit.probe: `client` (unavailable)
- **context**
  - context: `app_build` (unavailable)
  - context: `chip_model` (not_supported)
  - context: `container_mem_limit` (unavailable)
  - context: `device_llm` (not_applicable)
- **diarization_load**
  - diarization.load: `speakers_detected` (not_applicable)
  - diarization.load: `unknown_speaker_share` (not_applicable)
- **llm_call**
  - llm.note_write: `error_subtype` (unavailable)
  - llm.note_write: `http_status` (unavailable)
  - llm.provider_probe: `error_subtype` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - note_write (attempt 1): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 1): `model_load_seconds` (not_applicable)
  - note_write (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **postprocess_align**
  - asr.align: `duration_seconds` (not_applicable)
  - asr.align: `items` (not_applicable)
- **run**
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 113.29 s (54.1 %); language_detection 80.49 s (38.4 %); diarization_infer 7.22 s (3.4 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
