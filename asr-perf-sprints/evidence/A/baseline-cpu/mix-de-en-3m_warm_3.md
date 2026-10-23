# Diagnostics — recording bc8df152-2973-4c07-9bb6-667e9ae40d31

Run `3a756437-db87-4c46-9c31-fe855f01d0a6` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | bc8df152-2973-4c07-9bb6-667e9ae40d31 |
| processing_run_id | 3a756437-db87-4c46-9c31-fe855f01d0a6 |
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
| processing_wall_seconds | 313.18 s |
| rtf | 1.757 |
| speedup | 0.569 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.13 s | 0.0 % | -0.13 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.10 s |
| other | worker_job | 1 | ok | 303.79 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.00 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.16 s | 0.1 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.17 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.17 s |
| vad | · vad.speech_runs | 1 | ok | 3.08 s | 1.0 % | +0.17 s |
| language_detection | · lid.recording | 1 | ok | 5.49 s | 1.8 % | +3.25 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 1.7 % | +8.75 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 1.7 % | +14.02 s |
| language_detection | · lid.run | 1 | ok | 5.15 s | 1.6 % | +19.29 s |
| language_detection | · lid.run | 1 | ok | 5.24 s | 1.7 % | +24.44 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 1.6 % | +29.68 s |
| language_detection | · lid.run | 1 | ok | 5.01 s | 1.6 % | +34.74 s |
| language_detection | · lid.run | 1 | ok | 5.16 s | 1.6 % | +39.76 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 1.6 % | +44.92 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 1.6 % | +49.99 s |
| language_detection | · lid.run | 1 | ok | 5.14 s | 1.6 % | +55.01 s |
| language_detection | · lid.run | 1 | ok | 5.07 s | 1.6 % | +60.15 s |
| language_detection | · lid.run | 1 | ok | 5.00 s | 1.6 % | +65.23 s |
| language_detection | · lid.run | 1 | ok | 5.19 s | 1.7 % | +70.23 s |
| language_detection | · lid.run | 1 | ok | 5.07 s | 1.6 % | +75.42 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 1.6 % | +80.49 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 1.7 % | +85.59 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 1.6 % | +90.85 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 1.8 % | +95.96 s |
| language_detection | · lid.run | 1 | ok | 5.40 s | 1.7 % | +101.51 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 1.8 % | +106.92 s |
| language_detection | · lid.run | 1 | ok | 5.70 s | 1.8 % | +112.50 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 175.46 s | 56.0 % | +118.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.38 s | 2.7 % | +118.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.15 s | 2.6 % | +126.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.22 s | 2.3 % | +134.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 2.8 % | +141.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 2.6 % | +150.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.55 s | 2.7 % | +159.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.17 s | 2.6 % | +167.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.34 s | 2.7 % | +175.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.68 s | 2.5 % | +184.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.43 s | 2.4 % | +191.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.12 s | 2.3 % | +199.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.56 s | 2.4 % | +206.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.17 s | 2.3 % | +213.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.31 s | 2.0 % | +221.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.53 s | 2.7 % | +227.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.45 s | 3.0 % | +235.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.73 s | 2.8 % | +245.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.78 s | 2.8 % | +254.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.61 s | 2.7 % | +262.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.99 s | 2.5 % | +271.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.54 s | 2.4 % | +279.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.67 s | 2.1 % | +287.01 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +293.68 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +293.68 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +293.68 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +293.68 s |
| diarization_infer | · diarization.infer | 1 | ok | 10.10 s | 3.2 % | +293.68 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +303.78 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +303.79 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +303.79 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.82 s |
| queue | · asr.queue_wait | 1 | ok | 303.82 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.82 s |
| queue | · asr.queue_wait | 1 | ok | 303.82 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.83 s |
| queue | · asr.queue_wait | 1 | ok | 303.82 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.83 s |
| queue | · asr.queue_wait | 1 | ok | 303.83 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.70 s | 0.2 % | +304.77 s |
| other | notes.generate | 1 | ok | 7.71 s | — | +305.48 s |
| llm_call | · llm.note_write | 1 | ok | 7.60 s | 2.4 % | +305.54 s |

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
| lid.recording | 90.00 s | 5.49 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 5.27 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 5.27 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 5.15 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 5.24 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 5.06 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 5.01 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 5.16 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 5.06 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 5.03 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 5.14 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 5.07 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 5.00 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 5.19 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 5.07 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 5.10 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 5.26 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 5.10 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 5.55 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 5.40 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 5.58 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 5.70 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 8.38 s | 1.186 |
| asr.chunk | faster_whisper | 7.71 s | 8.15 s | 1.057 |
| asr.chunk | faster_whisper | 6.62 s | 7.22 s | 1.090 |
| asr.chunk | faster_whisper | 7.71 s | 8.88 s | 1.152 |
| asr.chunk | faster_whisper | 6.24 s | 8.08 s | 1.296 |
| asr.chunk | faster_whisper | 7.07 s | 8.55 s | 1.209 |
| asr.chunk | faster_whisper | 7.16 s | 8.17 s | 1.140 |
| asr.chunk | faster_whisper | 6.56 s | 8.34 s | 1.272 |
| asr.chunk | faster_whisper | 6.24 s | 7.68 s | 1.232 |
| asr.chunk | faster_whisper | 5.88 s | 7.43 s | 1.264 |
| asr.chunk | faster_whisper | 4.92 s | 7.12 s | 1.446 |
| asr.chunk | faster_whisper | 6.43 s | 7.56 s | 1.176 |
| asr.chunk | faster_whisper | 4.48 s | 7.17 s | 1.602 |
| asr.chunk | faster_whisper | 1.05 s | 6.31 s | 5.996 |
| asr.chunk | faster_whisper | 7.90 s | 8.53 s | 1.079 |
| asr.chunk | faster_whisper | 10.46 s | 9.45 s | 0.903 |
| asr.chunk | faster_whisper | 8.41 s | 8.73 s | 1.037 |
| asr.chunk | faster_whisper | 9.66 s | 8.78 s | 0.909 |
| asr.chunk | faster_whisper | 11.64 s | 8.61 s | 0.739 |
| asr.chunk | faster_whisper | 7.45 s | 7.99 s | 1.072 |
| asr.chunk | faster_whisper | 5.88 s | 7.54 s | 1.282 |
| asr.chunk | faster_whisper | 2.68 s | 6.67 s | 2.484 |

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
| infer | ok | 10.10 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.70 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.60 s | 2,071 | 0 | 0 | 536 | — (not_supported) |
| **total** |  | 2 |  |  | 8.30 s | 2,083 | 0 | 0 | 542 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,104,673,792 B (2.89 GiB) → 2,395,987,968 B (2.23 GiB) |
| swap used | 176,394,240 B (0.16 GiB) → 181,686,272 B (0.17 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
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

- Top critical-path stages: asr_primary 175.47 s (56.0 %); language_detection 114.91 s (36.7 %); diarization_infer 10.10 s (3.2 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.00 s.
- LLM latency share of wall: 2.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
