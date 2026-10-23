# Diagnostics — recording d7993aac-81fb-4aad-b473-c9cc7010b629

Run `aad77a39-8aee-4c62-b999-2d5bd11f3e3b` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | d7993aac-81fb-4aad-b473-c9cc7010b629 |
| processing_run_id | aad77a39-8aee-4c62-b999-2d5bd11f3e3b |
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
| processing_wall_seconds | 553.89 s |
| rtf | 3.107 |
| speedup | 0.322 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.09 s | 0.0 % | -0.14 s |
| other | worker_job | 1 | ok | 545.82 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.00 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.22 s | 0.0 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| vad | · vad.speech_runs | 1 | ok | 6.09 s | 1.1 % | +0.24 s |
| language_detection | · lid.recording | 1 | ok | 8.66 s | 1.6 % | +6.33 s |
| language_detection | · lid.run | 1 | ok | 8.87 s | 1.6 % | +14.99 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 1.6 % | +23.87 s |
| language_detection | · lid.run | 1 | ok | 8.29 s | 1.5 % | +32.99 s |
| language_detection | · lid.run | 1 | ok | 9.53 s | 1.7 % | +41.28 s |
| language_detection | · lid.run | 1 | ok | 10.40 s | 1.9 % | +50.82 s |
| language_detection | · lid.run | 1 | ok | 9.55 s | 1.7 % | +61.22 s |
| language_detection | · lid.run | 1 | ok | 9.38 s | 1.7 % | +70.77 s |
| language_detection | · lid.run | 1 | ok | 9.18 s | 1.7 % | +80.16 s |
| language_detection | · lid.run | 1 | ok | 9.46 s | 1.7 % | +89.34 s |
| language_detection | · lid.run | 1 | ok | 9.67 s | 1.7 % | +98.82 s |
| language_detection | · lid.run | 1 | ok | 9.68 s | 1.7 % | +108.49 s |
| language_detection | · lid.run | 1 | ok | 9.89 s | 1.8 % | +118.18 s |
| language_detection | · lid.run | 1 | ok | 9.94 s | 1.8 % | +128.08 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 1.7 % | +138.03 s |
| language_detection | · lid.run | 1 | ok | 9.17 s | 1.7 % | +147.18 s |
| language_detection | · lid.run | 1 | ok | 9.19 s | 1.7 % | +156.36 s |
| language_detection | · lid.run | 1 | ok | 9.30 s | 1.7 % | +165.55 s |
| language_detection | · lid.run | 1 | ok | 9.18 s | 1.7 % | +174.86 s |
| language_detection | · lid.run | 1 | ok | 9.19 s | 1.7 % | +184.04 s |
| language_detection | · lid.run | 1 | ok | 9.73 s | 1.8 % | +193.24 s |
| language_detection | · lid.run | 1 | ok | 9.48 s | 1.7 % | +202.98 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 315.08 s | 56.9 % | +212.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.02 s | 2.7 % | +212.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.76 s | 3.6 % | +227.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.67 s | 2.8 % | +247.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.84 s | 2.9 % | +262.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.90 s | 2.7 % | +278.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.88 s | 3.0 % | +293.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.29 s | 2.6 % | +310.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.63 s | 2.5 % | +324.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.60 s | 2.3 % | +338.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.52 s | 2.3 % | +351.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.68 s | 2.1 % | +363.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.71 s | 2.5 % | +375.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.31 s | 2.4 % | +389.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.37 s | 1.9 % | +402.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.73 s | 2.7 % | +412.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.47 s | 3.0 % | +427.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.94 s | 2.7 % | +443.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.55 s | 3.0 % | +458.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.32 s | 2.8 % | +475.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.23 s | 2.4 % | +490.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.81 s | 2.3 % | +503.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.73 s | 1.9 % | +516.81 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +527.54 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +527.54 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +527.55 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +527.55 s |
| diarization_infer | · diarization.infer | 1 | ok | 18.25 s | 3.3 % | +527.55 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +545.80 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +545.81 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +545.81 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.86 s |
| queue | · asr.queue_wait | 1 | ok | 545.86 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.87 s |
| queue | · asr.queue_wait | 1 | ok | 545.87 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.88 s |
| queue | · asr.queue_wait | 1 | ok | 545.87 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.88 s |
| queue | · asr.queue_wait | 1 | ok | 545.88 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.89 s |
| queue | · asr.queue_wait | 1 | ok | 545.88 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.89 s |
| queue | · asr.queue_wait | 1 | ok | 545.89 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.90 s |
| queue | · asr.queue_wait | 1 | ok | 545.89 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +545.90 s |
| queue | · asr.queue_wait | 1 | ok | 545.90 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.84 s | 0.2 % | +546.55 s |
| other | notes.generate | 1 | ok | 6.49 s | — | +547.40 s |
| llm_call | · llm.note_write | 1 | ok | 6.27 s | 1.1 % | +547.57 s |

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
| lid.recording | 90.00 s | 8.66 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 8.87 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 9.11 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 8.29 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 9.53 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 10.40 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 9.55 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 9.38 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 9.18 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 9.46 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 9.67 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 9.68 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 9.89 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 9.94 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 9.14 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 9.17 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 9.19 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 9.30 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 9.18 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 9.19 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 9.73 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 9.48 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 15.02 s | 2.125 |
| asr.chunk | faster_whisper | 7.71 s | 19.76 s | 2.564 |
| asr.chunk | faster_whisper | 6.62 s | 15.67 s | 2.367 |
| asr.chunk | faster_whisper | 7.71 s | 15.84 s | 2.055 |
| asr.chunk | faster_whisper | 6.24 s | 14.90 s | 2.389 |
| asr.chunk | faster_whisper | 7.07 s | 16.88 s | 2.388 |
| asr.chunk | faster_whisper | 7.16 s | 14.29 s | 1.994 |
| asr.chunk | faster_whisper | 6.56 s | 13.63 s | 2.080 |
| asr.chunk | faster_whisper | 6.24 s | 12.60 s | 2.021 |
| asr.chunk | faster_whisper | 5.88 s | 12.52 s | 2.127 |
| asr.chunk | faster_whisper | 4.92 s | 11.68 s | 2.372 |
| asr.chunk | faster_whisper | 6.43 s | 13.71 s | 2.133 |
| asr.chunk | faster_whisper | 4.48 s | 13.31 s | 2.974 |
| asr.chunk | faster_whisper | 1.05 s | 10.37 s | 9.860 |
| asr.chunk | faster_whisper | 7.90 s | 14.73 s | 1.865 |
| asr.chunk | faster_whisper | 10.46 s | 16.47 s | 1.575 |
| asr.chunk | faster_whisper | 8.41 s | 14.94 s | 1.776 |
| asr.chunk | faster_whisper | 9.66 s | 16.55 s | 1.713 |
| asr.chunk | faster_whisper | 11.64 s | 15.32 s | 1.316 |
| asr.chunk | faster_whisper | 7.45 s | 13.23 s | 1.775 |
| asr.chunk | faster_whisper | 5.88 s | 12.81 s | 2.178 |
| asr.chunk | faster_whisper | 2.68 s | 10.73 s | 3.996 |

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
| infer | ok | 18.25 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.84 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.27 s | 2,071 | 0 | 0 | 491 | — (not_supported) |
| **total** |  | 2 |  |  | 7.11 s | 2,083 | 0 | 0 | 497 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,422,652,928 B (2.26 GiB) → 2,997,362,688 B (2.79 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.09 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,650 B |

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

- Top critical-path stages: asr_primary 315.08 s (56.9 %); language_detection 206.02 s (37.2 %); diarization_infer 18.25 s (3.3 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.00 s.
- LLM latency share of wall: 1.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
