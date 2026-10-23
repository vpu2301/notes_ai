# Diagnostics — recording cb9ba0fa-8b13-43ee-b564-94332e80806a

Run `dae41d8c-8390-4873-8223-d106e586f681` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | cb9ba0fa-8b13-43ee-b564-94332e80806a |
| processing_run_id | dae41d8c-8390-4873-8223-d106e586f681 |
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
| processing_wall_seconds | 260.76 s |
| rtf | 2.290 |
| speedup | 0.437 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.14 s | 0.1 % | -0.15 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.13 s |
| other | worker_job | 1 | ok | 253.74 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.19 s | 0.1 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| vad | · vad.speech_runs | 1 | ok | 4.22 s | 1.6 % | +0.23 s |
| language_detection | · lid.recording | 1 | ok | 7.27 s | 2.8 % | +4.45 s |
| language_detection | · lid.run | 1 | ok | 6.25 s | 2.4 % | +11.72 s |
| language_detection | · lid.run | 1 | ok | 6.46 s | 2.5 % | +17.97 s |
| language_detection | · lid.run | 1 | ok | 6.81 s | 2.6 % | +24.43 s |
| language_detection | · lid.run | 1 | ok | 7.25 s | 2.8 % | +31.24 s |
| language_detection | · lid.run | 1 | ok | 6.65 s | 2.6 % | +38.50 s |
| language_detection | · lid.run | 1 | ok | 7.00 s | 2.7 % | +45.16 s |
| language_detection | · lid.run | 1 | ok | 8.59 s | 3.3 % | +52.16 s |
| language_detection | · lid.run | 1 | ok | 9.78 s | 3.8 % | +60.76 s |
| language_detection | · lid.run | 1 | ok | 7.20 s | 2.8 % | +70.57 s |
| language_detection | · lid.run | 1 | ok | 6.78 s | 2.6 % | +77.77 s |
| language_detection | · lid.run | 1 | ok | 7.30 s | 2.8 % | +84.56 s |
| language_detection | · lid.run | 1 | ok | 6.99 s | 2.7 % | +91.86 s |
| language_detection | · lid.run | 1 | ok | 7.34 s | 2.8 % | +98.86 s |
| language_detection | · lid.run | 1 | ok | 7.72 s | 3.0 % | +106.20 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 132.72 s | 50.9 % | +113.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.94 s | 4.2 % | +113.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.79 s | 3.8 % | +124.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.27 s | 3.6 % | +134.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.56 s | 4.0 % | +143.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 3.7 % | +154.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.35 s | 3.6 % | +164.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.12 s | 3.9 % | +173.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.78 s | 3.4 % | +183.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.00 s | 3.1 % | +192.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.53 s | 3.3 % | +200.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.07 s | 4.6 % | +209.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.36 s | 3.6 % | +221.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.91 s | 3.4 % | +230.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.29 s | 2.8 % | +239.36 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +246.64 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +246.65 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +246.65 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +246.65 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.08 s | 2.7 % | +246.65 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +253.73 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +253.73 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +253.73 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +253.78 s |
| queue | · asr.queue_wait | 1 | ok | 253.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +253.78 s |
| queue | · asr.queue_wait | 1 | ok | 253.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +253.78 s |
| queue | · asr.queue_wait | 1 | ok | 253.78 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.94 s | 0.4 % | +255.63 s |
| other | notes.generate | 1 | ok | 4.19 s | — | +256.57 s |
| llm_call | · llm.note_write | 1 | ok | 4.06 s | 1.6 % | +256.66 s |

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
| lid.recording | 90.00 s | 7.27 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 6.25 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 6.46 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 6.81 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 7.25 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 6.65 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 7.00 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 8.59 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 9.78 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 7.20 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 6.78 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 7.30 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 6.99 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 7.34 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 7.72 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 10.94 s | 1.702 |
| asr.chunk | faster_whisper | 7.23 s | 9.79 s | 1.354 |
| asr.chunk | faster_whisper | 6.88 s | 9.27 s | 1.348 |
| asr.chunk | faster_whisper | 6.75 s | 10.56 s | 1.564 |
| asr.chunk | faster_whisper | 7.26 s | 9.68 s | 1.334 |
| asr.chunk | faster_whisper | 7.93 s | 9.35 s | 1.178 |
| asr.chunk | faster_whisper | 8.86 s | 10.12 s | 1.142 |
| asr.chunk | faster_whisper | 5.31 s | 8.78 s | 1.655 |
| asr.chunk | faster_whisper | 5.34 s | 8.00 s | 1.498 |
| asr.chunk | faster_whisper | 5.79 s | 8.53 s | 1.474 |
| asr.chunk | faster_whisper | 17.12 s | 12.07 s | 0.705 |
| asr.chunk | faster_whisper | 8.38 s | 9.36 s | 1.117 |
| asr.chunk | faster_whisper | 4.73 s | 8.90 s | 1.882 |
| asr.chunk | faster_whisper | 2.83 s | 7.28 s | 2.570 |

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
| infer | ok | 7.08 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.94 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.06 s | 1,764 | 0 | 0 | 282 | — (not_supported) |
| **total** |  | 2 |  |  | 5.00 s | 1,776 | 0 | 0 | 288 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,115,409,408 B (2.90 GiB) → 3,093,147,648 B (2.88 GiB) |
| swap used | 31,252,480 B (0.03 GiB) → 31,252,480 B (0.03 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,602 B |

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

- Top critical-path stages: asr_primary 132.72 s (50.9 %); language_detection 109.39 s (41.9 %); diarization_infer 7.08 s (2.7 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: 1.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
