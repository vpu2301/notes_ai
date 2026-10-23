# Diagnostics — recording d89707cd-12fb-43aa-a116-f86e676a9e15

Run `1868da9b-1f36-45b4-9582-32a64e49c651` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | d89707cd-12fb-43aa-a116-f86e676a9e15 |
| processing_run_id | 1868da9b-1f36-45b4-9582-32a64e49c651 |
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
| processing_wall_seconds | 352.76 s |
| rtf | 1.979 |
| speedup | 0.505 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.13 s | 0.0 % | -0.13 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.12 s |
| other | worker_job | 1 | ok | 344.89 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.19 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.21 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.21 s |
| vad | · vad.speech_runs | 1 | ok | 2.91 s | 0.8 % | +0.21 s |
| language_detection | · lid.recording | 1 | ok | 5.96 s | 1.7 % | +3.15 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 1.6 % | +9.11 s |
| language_detection | · lid.run | 1 | ok | 5.44 s | 1.5 % | +14.90 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 1.5 % | +20.34 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 1.6 % | +25.60 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 1.6 % | +31.18 s |
| language_detection | · lid.run | 1 | ok | 6.16 s | 1.7 % | +36.66 s |
| language_detection | · lid.run | 1 | ok | 6.55 s | 1.9 % | +42.83 s |
| language_detection | · lid.run | 1 | ok | 7.54 s | 2.1 % | +49.38 s |
| language_detection | · lid.run | 1 | ok | 5.93 s | 1.7 % | +56.93 s |
| language_detection | · lid.run | 1 | ok | 5.87 s | 1.7 % | +62.87 s |
| language_detection | · lid.run | 1 | ok | 5.98 s | 1.7 % | +68.74 s |
| language_detection | · lid.run | 1 | ok | 5.84 s | 1.7 % | +74.72 s |
| language_detection | · lid.run | 1 | ok | 6.00 s | 1.7 % | +80.56 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 1.7 % | +86.56 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 1.7 % | +92.51 s |
| language_detection | · lid.run | 1 | ok | 6.00 s | 1.7 % | +98.45 s |
| language_detection | · lid.run | 1 | ok | 6.14 s | 1.7 % | +104.45 s |
| language_detection | · lid.run | 1 | ok | 6.54 s | 1.9 % | +110.59 s |
| language_detection | · lid.run | 1 | ok | 6.46 s | 1.8 % | +117.13 s |
| language_detection | · lid.run | 1 | ok | 6.05 s | 1.7 % | +123.59 s |
| language_detection | · lid.run | 1 | ok | 6.09 s | 1.7 % | +129.65 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 192.10 s | 54.5 % | +135.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.35 s | 2.4 % | +135.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.56 s | 2.7 % | +144.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.36 s | 2.4 % | +153.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.84 s | 2.5 % | +162.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.32 s | 2.4 % | +170.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.63 s | 2.4 % | +179.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.04 s | 2.6 % | +187.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.04 s | 2.6 % | +196.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.10 s | 2.3 % | +205.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.12 s | 2.3 % | +214.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.76 s | 2.2 % | +222.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.42 s | 2.4 % | +229.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.81 s | 2.2 % | +238.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.34 s | 1.8 % | +246.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.50 s | 2.4 % | +252.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.37 s | 2.4 % | +260.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.39 s | 2.4 % | +269.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.21 s | 2.6 % | +277.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.07 s | 3.1 % | +286.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.36 s | 3.2 % | +298.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.63 s | 3.0 % | +309.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.80 s | 2.2 % | +320.05 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +327.85 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +327.85 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +327.86 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +327.86 s |
| diarization_infer | · diarization.infer | 1 | ok | 16.96 s | 4.8 % | +327.86 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +344.81 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +344.82 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +344.82 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.92 s |
| queue | · asr.queue_wait | 1 | ok | 344.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.92 s |
| queue | · asr.queue_wait | 1 | ok | 344.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.93 s |
| queue | · asr.queue_wait | 1 | ok | 344.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.93 s |
| queue | · asr.queue_wait | 1 | ok | 344.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.94 s |
| queue | · asr.queue_wait | 1 | ok | 344.93 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.76 s | 0.2 % | +345.81 s |
| other | notes.generate | 1 | ok | 6.19 s | — | +346.57 s |
| llm_call | · llm.note_write | 1 | ok | 6.12 s | 1.7 % | +346.60 s |

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
| lid.recording | 90.00 s | 5.96 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 5.78 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 5.44 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 5.25 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 5.58 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 5.48 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 6.16 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 6.55 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 7.54 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 5.93 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 5.87 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 5.98 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 5.84 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 6.00 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 5.94 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 5.94 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 6.00 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 6.14 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 6.54 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 6.46 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 6.05 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 6.09 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 8.35 s | 1.181 |
| asr.chunk | faster_whisper | 7.71 s | 9.56 s | 1.240 |
| asr.chunk | faster_whisper | 6.62 s | 8.36 s | 1.263 |
| asr.chunk | faster_whisper | 7.71 s | 8.84 s | 1.147 |
| asr.chunk | faster_whisper | 6.24 s | 8.32 s | 1.334 |
| asr.chunk | faster_whisper | 7.07 s | 8.63 s | 1.221 |
| asr.chunk | faster_whisper | 7.16 s | 9.04 s | 1.262 |
| asr.chunk | faster_whisper | 6.56 s | 9.04 s | 1.379 |
| asr.chunk | faster_whisper | 6.24 s | 8.10 s | 1.299 |
| asr.chunk | faster_whisper | 5.88 s | 8.12 s | 1.380 |
| asr.chunk | faster_whisper | 4.92 s | 7.76 s | 1.576 |
| asr.chunk | faster_whisper | 6.43 s | 8.42 s | 1.309 |
| asr.chunk | faster_whisper | 4.48 s | 7.81 s | 1.746 |
| asr.chunk | faster_whisper | 1.05 s | 6.33 s | 6.022 |
| asr.chunk | faster_whisper | 7.90 s | 8.50 s | 1.076 |
| asr.chunk | faster_whisper | 10.46 s | 8.37 s | 0.800 |
| asr.chunk | faster_whisper | 8.41 s | 8.39 s | 0.997 |
| asr.chunk | faster_whisper | 9.66 s | 9.21 s | 0.953 |
| asr.chunk | faster_whisper | 11.64 s | 11.07 s | 0.951 |
| asr.chunk | faster_whisper | 7.45 s | 11.36 s | 1.525 |
| asr.chunk | faster_whisper | 5.88 s | 10.63 s | 1.806 |
| asr.chunk | faster_whisper | 2.68 s | 7.80 s | 2.906 |

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
| infer | ok | 16.96 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.76 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.12 s | 2,071 | 0 | 0 | 420 | — (not_supported) |
| **total** |  | 2 |  |  | 6.87 s | 2,083 | 0 | 0 | 426 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,989,899,776 B (2.78 GiB) → 3,116,933,120 B (2.90 GiB) |
| swap used | 154,611,712 B (0.14 GiB) → 156,610,560 B (0.15 GiB) |
| memory pressure | some_avg10=0.05 → some_avg10=0.59 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,646 B |

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

- Top critical-path stages: asr_primary 192.10 s (54.5 %); language_detection 132.52 s (37.6 %); diarization_infer 16.96 s (4.8 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
