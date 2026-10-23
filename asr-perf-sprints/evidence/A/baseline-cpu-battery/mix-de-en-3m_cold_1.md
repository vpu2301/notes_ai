# Diagnostics — recording bcdf1811-5040-4021-bf79-6af034a014b3

Run `3119e643-8096-42ea-822d-58b8d5865cf6` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | bcdf1811-5040-4021-bf79-6af034a014b3 |
| processing_run_id | 3119e643-8096-42ea-822d-58b8d5865cf6 |
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
| processing_wall_seconds | 410.02 s |
| rtf | 2.300 |
| speedup | 0.435 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.10 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 372.22 s | — | +28.03 s |
| queue | · asr.queue_wait | 1 | ok | 28.03 s | 6.8 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.06 s | 0.3 % | +28.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +29.10 s |
| model_init | · vad.model | 1 | ok | 2.82 s | 0.7 % | +29.10 s |
| vad | · vad.speech_runs | 1 | ok | 5.68 s | 1.4 % | +31.93 s |
| language_detection | · lid.recording | 1 | ok | 9.62 s | 2.3 % | +37.61 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 2.2 % | +47.24 s |
| language_detection | · lid.run | 1 | ok | 9.53 s | 2.3 % | +56.26 s |
| language_detection | · lid.run | 1 | ok | 8.42 s | 2.1 % | +65.79 s |
| language_detection | · lid.run | 1 | ok | 8.67 s | 2.1 % | +74.22 s |
| language_detection | · lid.run | 1 | ok | 10.18 s | 2.5 % | +82.90 s |
| language_detection | · lid.run | 1 | ok | 10.16 s | 2.5 % | +93.09 s |
| language_detection | · lid.run | 1 | ok | 8.81 s | 2.1 % | +103.26 s |
| language_detection | · lid.run | 1 | ok | 9.80 s | 2.4 % | +112.07 s |
| language_detection | · lid.run | 1 | ok | 11.03 s | 2.7 % | +121.88 s |
| language_detection | · lid.run | 1 | ok | 8.95 s | 2.2 % | +132.92 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 2.4 % | +141.88 s |
| language_detection | · lid.run | 1 | ok | 9.21 s | 2.2 % | +151.60 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 2.2 % | +160.81 s |
| language_detection | · lid.run | 1 | ok | 9.52 s | 2.3 % | +169.83 s |
| language_detection | · lid.run | 1 | ok | 8.94 s | 2.2 % | +179.36 s |
| language_detection | · lid.run | 1 | ok | 9.34 s | 2.3 % | +188.31 s |
| language_detection | · lid.run | 1 | ok | 8.69 s | 2.1 % | +197.65 s |
| language_detection | · lid.run | 1 | ok | 9.80 s | 2.4 % | +206.35 s |
| language_detection | · lid.run | 1 | ok | 9.90 s | 2.4 % | +216.16 s |
| language_detection | · lid.run | 1 | ok | 8.91 s | 2.2 % | +226.08 s |
| language_detection | · lid.run | 1 | ok | 6.12 s | 1.5 % | +235.00 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 144.85 s | 35.3 % | +241.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.75 s | 1.6 % | +241.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.12 s | 1.5 % | +247.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.36 s | 1.6 % | +254.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.66 s | 1.6 % | +260.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.39 s | 1.6 % | +267.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.00 s | 1.7 % | +273.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.78 s | 1.7 % | +280.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.37 s | 1.6 % | +287.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.68 s | 1.6 % | +293.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.31 s | 1.5 % | +300.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.86 s | 1.4 % | +306.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.16 s | 1.5 % | +312.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.02 s | 1.5 % | +318.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.07 s | 1.2 % | +324.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.80 s | 1.9 % | +329.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.25 s | 1.8 % | +337.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.03 s | 1.7 % | +344.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.57 s | 1.8 % | +351.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.69 s | 1.9 % | +359.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.83 s | 1.7 % | +367.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.43 s | 1.6 % | +373.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.64 s | 1.4 % | +380.32 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +385.97 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +385.99 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +385.99 s |
| diarization_load | · diarization.load | 1 | ok | 1.96 s | 0.5 % | +385.99 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.24 s | 3.0 % | +387.95 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +400.20 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +400.20 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +400.20 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.26 s |
| queue | · asr.queue_wait | 1 | ok | 400.25 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.26 s |
| queue | · asr.queue_wait | 1 | ok | 400.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.26 s |
| queue | · asr.queue_wait | 1 | ok | 400.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.27 s |
| queue | · asr.queue_wait | 1 | ok | 400.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.27 s |
| queue | · asr.queue_wait | 1 | ok | 400.26 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +400.27 s |
| queue | · asr.queue_wait | 1 | ok | 400.27 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.81 s | 0.2 % | +401.46 s |
| other | notes.generate | 1 | ok | 7.75 s | — | +402.27 s |
| llm_call | · llm.note_write | 1 | ok | 7.64 s | 1.9 % | +402.33 s |

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
| lid.recording | 90.00 s | 9.62 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 9.02 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 9.53 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 8.42 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 8.67 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 10.18 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 10.16 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 8.81 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 9.80 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 11.03 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 8.95 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 9.71 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 9.21 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 9.02 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 9.52 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 8.94 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 9.34 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 8.69 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 9.80 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 9.90 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 8.91 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 6.12 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 6.75 s | 0.955 |
| asr.chunk | faster_whisper | 7.71 s | 6.12 s | 0.794 |
| asr.chunk | faster_whisper | 6.62 s | 6.36 s | 0.961 |
| asr.chunk | faster_whisper | 7.71 s | 6.66 s | 0.864 |
| asr.chunk | faster_whisper | 6.24 s | 6.39 s | 1.024 |
| asr.chunk | faster_whisper | 7.07 s | 6.99 s | 0.989 |
| asr.chunk | faster_whisper | 7.16 s | 6.78 s | 0.946 |
| asr.chunk | faster_whisper | 6.56 s | 6.37 s | 0.971 |
| asr.chunk | faster_whisper | 6.24 s | 6.68 s | 1.072 |
| asr.chunk | faster_whisper | 5.88 s | 6.31 s | 1.073 |
| asr.chunk | faster_whisper | 4.92 s | 5.86 s | 1.190 |
| asr.chunk | faster_whisper | 6.43 s | 6.16 s | 0.959 |
| asr.chunk | faster_whisper | 4.48 s | 6.02 s | 1.346 |
| asr.chunk | faster_whisper | 1.05 s | 5.07 s | 4.816 |
| asr.chunk | faster_whisper | 7.90 s | 7.80 s | 0.987 |
| asr.chunk | faster_whisper | 10.46 s | 7.25 s | 0.694 |
| asr.chunk | faster_whisper | 8.41 s | 7.03 s | 0.836 |
| asr.chunk | faster_whisper | 9.66 s | 7.57 s | 0.783 |
| asr.chunk | faster_whisper | 11.64 s | 7.69 s | 0.660 |
| asr.chunk | faster_whisper | 7.45 s | 6.83 s | 0.916 |
| asr.chunk | faster_whisper | 5.88 s | 6.43 s | 1.093 |
| asr.chunk | faster_whisper | 2.68 s | 5.64 s | 2.101 |

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
| load | ok | 1.96 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 12.24 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.81 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.64 s | 2,071 | 0 | 0 | 491 | — (not_supported) |
| **total** |  | 2 |  |  | 8.45 s | 2,083 | 0 | 0 | 497 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,567,808 B (2.29 GiB) → 2,412,044,288 B (2.25 GiB) |
| swap used | 1,426,161,664 B (1.33 GiB) → 1,426,231,296 B (1.33 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.16 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,223 B |

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

- Top critical-path stages: language_detection 203.36 s (49.6 %); asr_primary 144.85 s (35.3 %); queue 28.03 s (6.8 %).
- Reprocessing ratio: 0.837.
- Cold loads: vad.model 2.82 s; diarization.load 1.96 s.
- Queue wait: 28.03 s.
- LLM latency share of wall: 2.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
