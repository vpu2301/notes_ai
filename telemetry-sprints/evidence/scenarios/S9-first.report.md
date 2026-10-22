# Diagnostics — recording 64eed3a7-cf18-47d2-b76f-3da80049ff91

Run `e608a97d-fede-4b4d-8fb5-1384f247a82b` · initial · partial

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 64eed3a7-cf18-47d2-b76f-3da80049ff91 |
| processing_run_id | e608a97d-fede-4b4d-8fb5-1384f247a82b |
| kind | initial |
| trigger | user |
| status | partial |
| error category | llm |
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
| llm | dev_mac | notes-chat | — | — | — | — | — |
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 120.00 s |
| processing_wall_seconds | 521.97 s |
| rtf | 4.350 |
| speedup | 0.230 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | 532.38 s |
| time_to_speaker_labels_seconds | 532.38 s |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.36 s | 0.1 % | -0.37 s |
| capture_input | asr.submit.probe | 1 | ok | 0.19 s | 0.0 % | -0.31 s |
| other | worker_job | 1 | ok | 289.12 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.25 s | 0.0 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| vad | · vad.speech_runs | 1 | ok | 5.86 s | 1.1 % | +0.30 s |
| language_detection | · lid.run | 1 | ok | 12.45 s | 2.4 % | +6.17 s |
| language_detection | · lid.run | 1 | ok | 16.03 s | 3.1 % | +18.63 s |
| language_detection | · lid.run | 1 | ok | 12.58 s | 2.4 % | +34.69 s |
| language_detection | · lid.run | 1 | ok | 11.96 s | 2.3 % | +47.34 s |
| language_detection | · lid.run | 1 | ok | 11.57 s | 2.2 % | +59.31 s |
| language_detection | · lid.run | 1 | ok | 11.91 s | 2.3 % | +70.89 s |
| language_detection | · lid.run | 1 | ok | 11.23 s | 2.2 % | +82.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 176.31 s | 33.8 % | +94.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 32.48 s | 6.2 % | +94.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.75 s | 2.8 % | +126.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.06 s | 3.8 % | +141.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.48 s | 7.9 % | +161.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 30.18 s | 5.8 % | +202.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.83 s | 4.2 % | +233.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.43 s | 3.0 % | +254.92 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +270.36 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +270.39 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +270.39 s |
| diarization_load | · diarization.load | 1 | ok | 3.48 s | 0.7 % | +270.39 s |
| diarization_infer | · diarization.infer | 1 | ok | 15.14 s | 2.9 % | +273.88 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +289.02 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +289.03 s |
| persist | · asr.persist | 1 | ok | 0.11 s | 0.0 % | +289.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.17 s |
| queue | · asr.queue_wait | 1 | ok | 289.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.18 s |
| queue | · asr.queue_wait | 1 | ok | 289.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.19 s |
| queue | · asr.queue_wait | 1 | ok | 289.18 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.19 s |
| queue | · asr.queue_wait | 1 | ok | 289.19 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +466.48 s |
| llm_call | llm.provider_probe | 1 | error | 0.03 s | 0.0 % | +467.50 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +469.53 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +485.08 s |
| llm_call | llm.provider_probe | 2 | error | 0.05 s | 0.0 % | +486.10 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +488.16 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +518.91 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +519.94 s |
| llm_call | llm.provider_probe | 3 | error | 0.02 s | 0.0 % | +521.95 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 115.72 s | 7 | 4.73 s | 18.81 s | 29.98 s |

### Language checks

Language checks: 7.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 12.45 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 16.03 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 12.58 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 11.96 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 11.57 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 11.91 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 11.23 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 32.48 s | 1.408 |
| asr.chunk | faster_whisper | 5.08 s | 14.75 s | 2.901 |
| asr.chunk | faster_whisper | 14.36 s | 20.06 s | 1.396 |
| asr.chunk | faster_whisper | 29.98 s | 41.48 s | 1.384 |
| asr.chunk | faster_whisper | 19.68 s | 30.18 s | 1.534 |
| asr.chunk | faster_whisper | 18.81 s | 21.83 s | 1.160 |
| asr.chunk | faster_whisper | 4.73 s | 15.43 s | 3.260 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 115.72 s |
| audio duration | 120.00 s |
| reprocessing ratio | 0.964 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.48 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 15.14 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.03 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.05 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| **total** |  | 9 |  |  | 0.16 s | 72 | — | — | — |  |

Token accounting: estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,601,766,912 B (2.42 GiB) → 2,989,711,360 B (2.78 GiB) |
| swap used | 1,286,168,576 B (1.20 GiB) → 1,277,231,104 B (1.19 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.35 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.23 s |
| telemetry buffer peak | 1,310 B |

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
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 2): `completion_chars` (unavailable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `output_tokens` (unavailable)
  - provider_probe (attempt 2): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 3): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 3): `completion_chars` (unavailable)
  - provider_probe (attempt 3): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 3): `model_load_seconds` (unavailable)
  - provider_probe (attempt 3): `output_tokens` (unavailable)
  - provider_probe (attempt 3): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 3): `time_to_first_token_seconds` (not_applicable)
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
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 176.31 s (33.8 %); language_detection 87.74 s (16.8 %); diarization_infer 15.14 s (2.9 %).
- Reprocessing ratio: 0.964.
- Cold loads: diarization.load 3.48 s.
- Queue wait: 0.02 s.
- LLM latency share of wall: 0.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
