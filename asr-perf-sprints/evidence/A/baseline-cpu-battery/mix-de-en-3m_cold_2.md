# Diagnostics — recording a1bf7640-3b51-4ace-b89f-0db135f4ee39

Run `42c86f4b-ba0a-4b19-8e59-ed9619402c64` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | a1bf7640-3b51-4ace-b89f-0db135f4ee39 |
| processing_run_id | 42c86f4b-ba0a-4b19-8e59-ed9619402c64 |
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
| processing_wall_seconds | 311.32 s |
| rtf | 1.747 |
| speedup | 0.573 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.09 s | 0.0 % | -0.12 s |
| other | worker_job | 1 | ok | 290.70 s | — | +12.89 s |
| queue | · asr.queue_wait | 1 | ok | 12.89 s | 4.1 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.46 s | 0.1 % | +12.90 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +13.36 s |
| model_init | · vad.model | 1 | ok | 1.36 s | 0.4 % | +13.36 s |
| vad | · vad.speech_runs | 1 | ok | 5.66 s | 1.8 % | +14.73 s |
| language_detection | · lid.recording | 1 | ok | 4.66 s | 1.5 % | +20.39 s |
| language_detection | · lid.run | 1 | ok | 4.55 s | 1.5 % | +25.06 s |
| language_detection | · lid.run | 1 | ok | 4.58 s | 1.5 % | +29.61 s |
| language_detection | · lid.run | 1 | ok | 4.62 s | 1.5 % | +34.19 s |
| language_detection | · lid.run | 1 | ok | 4.91 s | 1.6 % | +38.81 s |
| language_detection | · lid.run | 1 | ok | 4.81 s | 1.5 % | +43.72 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 1.5 % | +48.53 s |
| language_detection | · lid.run | 1 | ok | 4.43 s | 1.4 % | +53.14 s |
| language_detection | · lid.run | 1 | ok | 4.13 s | 1.3 % | +57.58 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 1.6 % | +61.71 s |
| language_detection | · lid.run | 1 | ok | 4.74 s | 1.5 % | +66.61 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 1.6 % | +71.36 s |
| language_detection | · lid.run | 1 | ok | 4.29 s | 1.4 % | +76.25 s |
| language_detection | · lid.run | 1 | ok | 4.75 s | 1.5 % | +80.54 s |
| language_detection | · lid.run | 1 | ok | 4.79 s | 1.5 % | +85.30 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 1.6 % | +90.09 s |
| language_detection | · lid.run | 1 | ok | 4.43 s | 1.4 % | +94.92 s |
| language_detection | · lid.run | 1 | ok | 4.82 s | 1.5 % | +99.36 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 1.5 % | +104.18 s |
| language_detection | · lid.run | 1 | ok | 4.64 s | 1.5 % | +108.83 s |
| language_detection | · lid.run | 1 | ok | 4.71 s | 1.5 % | +113.48 s |
| language_detection | · lid.run | 1 | ok | 4.34 s | 1.4 % | +118.19 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 168.25 s | 54.0 % | +122.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.15 s | 2.3 % | +122.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.32 s | 2.4 % | +129.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.61 s | 2.1 % | +137.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.98 s | 2.2 % | +143.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.85 s | 2.2 % | +150.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.97 s | 2.6 % | +157.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.82 s | 2.5 % | +165.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.98 s | 2.2 % | +173.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.08 s | 2.3 % | +180.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.12 s | 2.3 % | +187.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.61 s | 2.1 % | +194.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.93 s | 2.2 % | +201.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.51 s | 2.4 % | +207.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.94 s | 1.9 % | +215.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.02 s | 2.6 % | +221.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.05 s | 3.2 % | +229.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.16 s | 2.9 % | +239.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.02 s | 2.9 % | +248.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.21 s | 3.0 % | +257.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.15 s | 2.6 % | +266.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.32 s | 2.7 % | +275.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.36 s | 2.4 % | +283.41 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +290.78 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +290.80 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +290.81 s |
| diarization_load | · diarization.load | 1 | ok | 2.34 s | 0.8 % | +290.81 s |
| diarization_infer | · diarization.infer | 1 | ok | 10.40 s | 3.3 % | +293.15 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +303.55 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +303.55 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +303.56 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.60 s |
| queue | · asr.queue_wait | 1 | ok | 303.59 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.60 s |
| queue | · asr.queue_wait | 1 | ok | 303.60 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.61 s |
| queue | · asr.queue_wait | 1 | ok | 303.60 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +303.61 s |
| queue | · asr.queue_wait | 1 | ok | 303.60 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.83 s | 0.3 % | +304.94 s |
| other | notes.generate | 1 | ok | 5.55 s | — | +305.77 s |
| llm_call | · llm.note_write | 1 | ok | 5.45 s | 1.8 % | +305.82 s |

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
| lid.recording | 90.00 s | 4.66 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 4.55 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 4.58 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 4.62 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 4.91 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 4.81 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 4.61 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 4.43 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 4.13 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 4.90 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 4.74 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 4.89 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 4.29 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 4.75 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 4.79 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 4.83 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 4.43 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 4.82 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 4.65 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 4.64 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 4.71 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 4.34 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 7.15 s | 1.012 |
| asr.chunk | faster_whisper | 7.71 s | 7.32 s | 0.949 |
| asr.chunk | faster_whisper | 6.62 s | 6.61 s | 0.998 |
| asr.chunk | faster_whisper | 7.71 s | 6.98 s | 0.905 |
| asr.chunk | faster_whisper | 6.24 s | 6.85 s | 1.098 |
| asr.chunk | faster_whisper | 7.07 s | 7.97 s | 1.127 |
| asr.chunk | faster_whisper | 7.16 s | 7.82 s | 1.091 |
| asr.chunk | faster_whisper | 6.56 s | 6.98 s | 1.064 |
| asr.chunk | faster_whisper | 6.24 s | 7.08 s | 1.135 |
| asr.chunk | faster_whisper | 5.88 s | 7.12 s | 1.210 |
| asr.chunk | faster_whisper | 4.92 s | 6.61 s | 1.343 |
| asr.chunk | faster_whisper | 6.43 s | 6.93 s | 1.078 |
| asr.chunk | faster_whisper | 4.48 s | 7.51 s | 1.678 |
| asr.chunk | faster_whisper | 1.05 s | 5.94 s | 5.642 |
| asr.chunk | faster_whisper | 7.90 s | 8.02 s | 1.015 |
| asr.chunk | faster_whisper | 10.46 s | 10.05 s | 0.961 |
| asr.chunk | faster_whisper | 8.41 s | 9.16 s | 1.089 |
| asr.chunk | faster_whisper | 9.66 s | 9.02 s | 0.934 |
| asr.chunk | faster_whisper | 11.64 s | 9.21 s | 0.791 |
| asr.chunk | faster_whisper | 7.45 s | 8.15 s | 1.094 |
| asr.chunk | faster_whisper | 5.88 s | 8.32 s | 1.415 |
| asr.chunk | faster_whisper | 2.68 s | 7.35 s | 2.740 |

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
| load | ok | 2.34 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 10.40 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.83 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.45 s | 2,071 | 0 | 0 | 424 | — (not_supported) |
| **total** |  | 2 |  |  | 6.28 s | 2,083 | 0 | 0 | 430 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,291,008 B (2.28 GiB) → 3,044,044,800 B (2.83 GiB) |
| swap used | 1,427,767,296 B (1.33 GiB) → 1,430,020,096 B (1.33 GiB) |
| memory pressure | some_avg10=0.01 → some_avg10=0.51 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,227 B |

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

- Top critical-path stages: asr_primary 168.25 s (54.0 %); language_detection 102.08 s (32.8 %); queue 12.89 s (4.1 %).
- Reprocessing ratio: 0.837.
- Cold loads: vad.model 1.36 s; diarization.load 2.34 s.
- Queue wait: 12.89 s.
- LLM latency share of wall: 2.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
