# Diagnostics — recording 282f9ec6-0a72-4cca-a896-68376ebed1fc

Run `0f8a80e1-9f8f-4a3a-abea-e55d519b83fb` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 282f9ec6-0a72-4cca-a896-68376ebed1fc |
| processing_run_id | 0f8a80e1-9f8f-4a3a-abea-e55d519b83fb |
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
| audio duration | 178.25 s |
| processing_wall_seconds | 351.21 s |
| rtf | 1.970 |
| speedup | 0.508 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.13 s |
| other | worker_job | 1 | ok | 342.65 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.20 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| vad | · vad.speech_runs | 1 | ok | 3.32 s | 0.9 % | +0.23 s |
| language_detection | · lid.recording | 1 | ok | 5.31 s | 1.5 % | +3.55 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 1.6 % | +8.86 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 1.7 % | +14.64 s |
| language_detection | · lid.run | 1 | ok | 5.86 s | 1.7 % | +20.70 s |
| language_detection | · lid.run | 1 | ok | 6.61 s | 1.9 % | +26.57 s |
| language_detection | · lid.run | 1 | ok | 6.33 s | 1.8 % | +33.19 s |
| language_detection | · lid.run | 1 | ok | 6.42 s | 1.8 % | +39.53 s |
| language_detection | · lid.run | 1 | ok | 6.30 s | 1.8 % | +45.96 s |
| language_detection | · lid.run | 1 | ok | 6.32 s | 1.8 % | +52.26 s |
| language_detection | · lid.run | 1 | ok | 6.01 s | 1.7 % | +58.58 s |
| language_detection | · lid.run | 1 | ok | 6.33 s | 1.8 % | +64.59 s |
| language_detection | · lid.run | 1 | ok | 6.18 s | 1.8 % | +70.93 s |
| language_detection | · lid.run | 1 | ok | 6.21 s | 1.8 % | +77.11 s |
| language_detection | · lid.run | 1 | ok | 6.06 s | 1.7 % | +83.32 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 1.6 % | +89.38 s |
| language_detection | · lid.run | 1 | ok | 6.41 s | 1.8 % | +95.05 s |
| language_detection | · lid.run | 1 | ok | 6.21 s | 1.8 % | +101.46 s |
| language_detection | · lid.run | 1 | ok | 5.88 s | 1.7 % | +107.67 s |
| language_detection | · lid.run | 1 | ok | 6.43 s | 1.8 % | +113.56 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 1.7 % | +120.00 s |
| language_detection | · lid.run | 1 | ok | 5.90 s | 1.7 % | +125.80 s |
| language_detection | · lid.run | 1 | ok | 6.04 s | 1.7 % | +131.71 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 194.06 s | 55.3 % | +137.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.42 s | 2.4 % | +137.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.63 s | 2.5 % | +146.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.92 s | 2.3 % | +154.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.52 s | 2.4 % | +162.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 2.6 % | +171.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.48 s | 2.7 % | +180.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.49 s | 2.4 % | +189.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.60 s | 2.4 % | +198.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.46 s | 2.4 % | +206.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.58 s | 2.4 % | +215.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.20 s | 2.3 % | +223.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.25 s | 2.6 % | +232.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.92 s | 2.5 % | +241.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.50 s | 2.1 % | +250.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.78 s | 2.8 % | +257.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.90 s | 2.8 % | +267.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.92 s | 2.8 % | +277.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.28 s | 3.2 % | +287.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.37 s | 2.7 % | +298.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.83 s | 2.5 % | +307.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.11 s | 2.3 % | +316.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.87 s | 2.0 % | +324.93 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +331.80 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +331.81 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +331.81 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +331.81 s |
| diarization_infer | · diarization.infer | 1 | ok | 10.63 s | 3.0 % | +331.81 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +342.45 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +342.45 s |
| persist | · asr.persist | 1 | ok | 0.21 s | 0.1 % | +342.45 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.68 s |
| queue | · asr.queue_wait | 1 | ok | 342.68 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.68 s |
| queue | · asr.queue_wait | 1 | ok | 342.68 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.69 s |
| queue | · asr.queue_wait | 1 | ok | 342.68 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.69 s |
| queue | · asr.queue_wait | 1 | ok | 342.69 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.65 s | 0.2 % | +344.18 s |
| other | notes.generate | 1 | ok | 6.38 s | — | +344.83 s |
| llm_call | · llm.note_write | 1 | ok | 6.28 s | 1.8 % | +344.88 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 149.22 s | 22 | 1.05 s | 6.84 s | 11.64 s |

### Language checks

Language checks: 22.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 5.31 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 5.77 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 6.07 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 5.86 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 6.61 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 6.33 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 6.42 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 6.30 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 6.32 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 6.01 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 6.33 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 6.18 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 6.21 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 6.06 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 5.67 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 6.41 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 6.21 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 5.88 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 6.43 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 5.81 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 5.90 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 6.04 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 8.42 s | 1.191 |
| asr.chunk | faster_whisper | 7.71 s | 8.63 s | 1.120 |
| asr.chunk | faster_whisper | 6.62 s | 7.92 s | 1.196 |
| asr.chunk | faster_whisper | 7.71 s | 8.52 s | 1.105 |
| asr.chunk | faster_whisper | 6.24 s | 8.96 s | 1.437 |
| asr.chunk | faster_whisper | 7.07 s | 9.48 s | 1.341 |
| asr.chunk | faster_whisper | 7.16 s | 8.49 s | 1.185 |
| asr.chunk | faster_whisper | 6.56 s | 8.60 s | 1.312 |
| asr.chunk | faster_whisper | 6.24 s | 8.46 s | 1.357 |
| asr.chunk | faster_whisper | 5.88 s | 8.58 s | 1.458 |
| asr.chunk | faster_whisper | 4.92 s | 8.20 s | 1.665 |
| asr.chunk | faster_whisper | 6.43 s | 9.25 s | 1.439 |
| asr.chunk | faster_whisper | 4.48 s | 8.92 s | 1.992 |
| asr.chunk | faster_whisper | 1.05 s | 7.50 s | 7.134 |
| asr.chunk | faster_whisper | 7.90 s | 9.78 s | 1.239 |
| asr.chunk | faster_whisper | 10.46 s | 9.90 s | 0.947 |
| asr.chunk | faster_whisper | 8.41 s | 9.92 s | 1.179 |
| asr.chunk | faster_whisper | 9.66 s | 11.28 s | 1.167 |
| asr.chunk | faster_whisper | 11.64 s | 9.37 s | 0.805 |
| asr.chunk | faster_whisper | 7.45 s | 8.83 s | 1.184 |
| asr.chunk | faster_whisper | 5.88 s | 8.11 s | 1.379 |
| asr.chunk | faster_whisper | 2.68 s | 6.87 s | 2.561 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 149.22 s |
| audio duration | 178.25 s |
| reprocessing ratio | 0.837 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 10.63 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.65 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.28 s | 2,071 | 0 | 0 | 442 | — (not_supported) |
| **total** |  | 2 |  |  | 6.93 s | 2,083 | 0 | 0 | 448 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,393,063,424 B (2.23 GiB) → 3,104,268,288 B (2.89 GiB) |
| swap used | 156,610,560 B (0.15 GiB) → 176,267,264 B (0.16 GiB) |
| memory pressure | some_avg10=0.14 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,645 B |

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

- Top critical-path stages: asr_primary 194.06 s (55.3 %); language_detection 134.13 s (38.2 %); diarization_infer 10.63 s (3.0 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
