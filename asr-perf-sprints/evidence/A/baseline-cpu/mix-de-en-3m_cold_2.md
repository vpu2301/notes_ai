# Diagnostics — recording 56365a2d-5090-4559-81e4-02843994383b

Run `ae9ed9f4-0998-472a-af8a-7b57d597c0ee` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 56365a2d-5090-4559-81e4-02843994383b |
| processing_run_id | ae9ed9f4-0998-472a-af8a-7b57d597c0ee |
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
| processing_wall_seconds | 425.15 s |
| rtf | 2.385 |
| speedup | 0.419 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.10 s | 0.0 % | -0.10 s |
| capture_input | asr.submit.probe | 1 | ok | 0.06 s | 0.0 % | -0.09 s |
| other | worker_job | 1 | ok | 368.88 s | — | +12.92 s |
| queue | · asr.queue_wait | 1 | ok | 12.91 s | 3.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.32 s | 0.1 % | +12.92 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +13.24 s |
| model_init | · vad.model | 1 | ok | 1.44 s | 0.3 % | +13.24 s |
| vad | · vad.speech_runs | 1 | ok | 4.20 s | 1.0 % | +14.68 s |
| language_detection | · lid.recording | 1 | ok | 6.08 s | 1.4 % | +18.88 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 1.3 % | +24.97 s |
| language_detection | · lid.run | 1 | ok | 5.45 s | 1.3 % | +30.37 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 1.3 % | +35.82 s |
| language_detection | · lid.run | 1 | ok | 6.70 s | 1.6 % | +41.30 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 1.3 % | +47.99 s |
| language_detection | · lid.run | 1 | ok | 5.85 s | 1.4 % | +53.47 s |
| language_detection | · lid.run | 1 | ok | 5.95 s | 1.4 % | +59.32 s |
| language_detection | · lid.run | 1 | ok | 5.65 s | 1.3 % | +65.27 s |
| language_detection | · lid.run | 1 | ok | 5.80 s | 1.4 % | +70.92 s |
| language_detection | · lid.run | 1 | ok | 6.88 s | 1.6 % | +76.74 s |
| language_detection | · lid.run | 1 | ok | 6.66 s | 1.6 % | +83.62 s |
| language_detection | · lid.run | 1 | ok | 6.35 s | 1.5 % | +90.29 s |
| language_detection | · lid.run | 1 | ok | 6.58 s | 1.5 % | +96.64 s |
| language_detection | · lid.run | 1 | ok | 6.61 s | 1.6 % | +103.24 s |
| language_detection | · lid.run | 1 | ok | 6.92 s | 1.6 % | +109.85 s |
| language_detection | · lid.run | 1 | ok | 6.22 s | 1.5 % | +116.78 s |
| language_detection | · lid.run | 1 | ok | 6.23 s | 1.5 % | +123.00 s |
| language_detection | · lid.run | 1 | ok | 6.24 s | 1.5 % | +129.23 s |
| language_detection | · lid.run | 1 | ok | 6.54 s | 1.5 % | +135.48 s |
| language_detection | · lid.run | 1 | ok | 6.81 s | 1.6 % | +142.03 s |
| language_detection | · lid.run | 1 | ok | 5.91 s | 1.4 % | +148.84 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 214.51 s | 50.5 % | +154.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.78 s | 2.3 % | +154.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.21 s | 2.4 % | +164.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.36 s | 2.4 % | +174.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.61 s | 2.3 % | +185.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.27 s | 2.4 % | +194.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.27 s | 2.4 % | +205.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.41 s | 2.4 % | +215.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.73 s | 2.5 % | +225.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.06 s | 2.4 % | +236.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.14 s | 2.6 % | +246.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.08 s | 2.6 % | +257.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.58 s | 2.3 % | +268.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.39 s | 2.2 % | +278.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.62 s | 1.8 % | +287.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.21 s | 2.2 % | +295.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.09 s | 2.1 % | +304.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.98 s | 2.3 % | +313.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.66 s | 2.5 % | +323.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.92 s | 2.3 % | +334.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.99 s | 2.1 % | +344.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.72 s | 2.1 % | +353.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.25 s | 1.7 % | +362.01 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +369.26 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +369.29 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +369.30 s |
| diarization_load | · diarization.load | 1 | ok | 1.68 s | 0.4 % | +369.30 s |
| diarization_infer | · diarization.infer | 1 | ok | 10.79 s | 2.5 % | +370.98 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +381.77 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +381.78 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +381.78 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.82 s |
| queue | · asr.queue_wait | 1 | ok | 381.82 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.82 s |
| queue | · asr.queue_wait | 1 | ok | 381.82 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.83 s |
| queue | · asr.queue_wait | 1 | ok | 381.82 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.83 s |
| queue | · asr.queue_wait | 1 | ok | 381.82 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.83 s |
| queue | · asr.queue_wait | 1 | ok | 381.83 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +381.83 s |
| queue | · asr.queue_wait | 1 | ok | 381.83 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 35.98 s | 8.5 % | +383.06 s |
| other | notes.generate | 1 | ok | 6.11 s | — | +419.04 s |
| llm_call | · llm.note_write | 1 | ok | 6.01 s | 1.4 % | +419.10 s |

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
| lid.recording | 90.00 s | 6.08 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 5.39 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 5.45 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 5.48 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 6.70 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 5.48 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 5.85 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 5.95 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 5.65 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 5.80 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 6.88 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 6.66 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 6.35 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 6.58 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 6.61 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 6.92 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 6.22 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 6.23 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 6.24 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 6.54 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 6.81 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 5.91 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 9.78 s | 1.384 |
| asr.chunk | faster_whisper | 7.71 s | 10.21 s | 1.325 |
| asr.chunk | faster_whisper | 6.62 s | 10.36 s | 1.566 |
| asr.chunk | faster_whisper | 7.71 s | 9.61 s | 1.247 |
| asr.chunk | faster_whisper | 6.24 s | 10.27 s | 1.647 |
| asr.chunk | faster_whisper | 7.07 s | 10.27 s | 1.453 |
| asr.chunk | faster_whisper | 7.16 s | 10.41 s | 1.454 |
| asr.chunk | faster_whisper | 6.56 s | 10.73 s | 1.636 |
| asr.chunk | faster_whisper | 6.24 s | 10.06 s | 1.613 |
| asr.chunk | faster_whisper | 5.88 s | 11.14 s | 1.894 |
| asr.chunk | faster_whisper | 4.92 s | 11.08 s | 2.250 |
| asr.chunk | faster_whisper | 6.43 s | 9.58 s | 1.490 |
| asr.chunk | faster_whisper | 4.48 s | 9.39 s | 2.097 |
| asr.chunk | faster_whisper | 1.05 s | 7.62 s | 7.240 |
| asr.chunk | faster_whisper | 7.90 s | 9.21 s | 1.166 |
| asr.chunk | faster_whisper | 10.46 s | 9.09 s | 0.869 |
| asr.chunk | faster_whisper | 8.41 s | 9.98 s | 1.186 |
| asr.chunk | faster_whisper | 9.66 s | 10.66 s | 1.103 |
| asr.chunk | faster_whisper | 11.64 s | 9.92 s | 0.852 |
| asr.chunk | faster_whisper | 7.45 s | 8.99 s | 1.207 |
| asr.chunk | faster_whisper | 5.88 s | 8.72 s | 1.481 |
| asr.chunk | faster_whisper | 2.68 s | 7.25 s | 2.702 |

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
| load | ok | 1.68 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 10.79 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 35.98 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.00 s | 2,071 | 0 | 0 | 420 | — (not_supported) |
| **total** |  | 2 |  |  | 41.98 s | 2,083 | 0 | 0 | 426 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,455,912,448 B (2.29 GiB) → 3,035,119,616 B (2.83 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
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

- Top critical-path stages: asr_primary 214.51 s (50.5 %); language_detection 135.79 s (31.9 %); llm_call 41.98 s (9.9 %).
- Reprocessing ratio: 0.837.
- Cold loads: vad.model 1.44 s; diarization.load 1.68 s.
- Queue wait: 12.91 s.
- LLM latency share of wall: 9.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
