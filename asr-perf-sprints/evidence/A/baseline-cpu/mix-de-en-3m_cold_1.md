# Diagnostics — recording 518933c1-d291-4421-8340-5454c943109d

Run `f6c4fc53-43f4-402b-ab46-45b685d463bb` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 518933c1-d291-4421-8340-5454c943109d |
| processing_run_id | f6c4fc53-43f4-402b-ab46-45b685d463bb |
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
| processing_wall_seconds | 358.96 s |
| rtf | 2.014 |
| speedup | 0.497 |
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
| other | worker_job | 1 | ok | 337.32 s | — | +12.82 s |
| queue | · asr.queue_wait | 1 | ok | 12.81 s | 3.6 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.35 s | 0.1 % | +12.82 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +13.17 s |
| model_init | · vad.model | 1 | ok | 1.44 s | 0.4 % | +13.17 s |
| vad | · vad.speech_runs | 1 | ok | 3.53 s | 1.0 % | +14.61 s |
| language_detection | · lid.recording | 1 | ok | 6.05 s | 1.7 % | +18.15 s |
| language_detection | · lid.run | 1 | ok | 5.28 s | 1.5 % | +24.20 s |
| language_detection | · lid.run | 1 | ok | 5.12 s | 1.4 % | +29.49 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 1.5 % | +34.61 s |
| language_detection | · lid.run | 1 | ok | 5.05 s | 1.4 % | +39.88 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 1.6 % | +44.93 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 1.4 % | +50.52 s |
| language_detection | · lid.run | 1 | ok | 5.35 s | 1.5 % | +55.55 s |
| language_detection | · lid.run | 1 | ok | 5.41 s | 1.5 % | +60.90 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 1.6 % | +66.31 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 1.5 % | +72.05 s |
| language_detection | · lid.run | 1 | ok | 5.41 s | 1.5 % | +77.59 s |
| language_detection | · lid.run | 1 | ok | 6.28 s | 1.7 % | +83.00 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 1.6 % | +89.28 s |
| language_detection | · lid.run | 1 | ok | 6.22 s | 1.7 % | +95.10 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 1.6 % | +101.33 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 1.6 % | +107.08 s |
| language_detection | · lid.run | 1 | ok | 6.05 s | 1.7 % | +112.77 s |
| language_detection | · lid.run | 1 | ok | 5.79 s | 1.6 % | +118.83 s |
| language_detection | · lid.run | 1 | ok | 5.85 s | 1.6 % | +124.62 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 1.5 % | +130.47 s |
| language_detection | · lid.run | 1 | ok | 6.04 s | 1.7 % | +136.03 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 193.27 s | 53.8 % | +142.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.47 s | 2.4 % | +142.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.91 s | 2.5 % | +150.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.54 s | 2.4 % | +159.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.51 s | 2.4 % | +168.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.83 s | 2.5 % | +176.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.45 s | 2.6 % | +185.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.95 s | 2.5 % | +194.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.20 s | 2.6 % | +203.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.43 s | 2.3 % | +212.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.66 s | 2.4 % | +221.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.25 s | 2.3 % | +230.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.95 s | 2.2 % | +238.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.47 s | 2.4 % | +246.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.80 s | 1.9 % | +254.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.06 s | 2.5 % | +261.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.36 s | 2.6 % | +270.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.47 s | 2.6 % | +279.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.01 s | 2.8 % | +289.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.61 s | 2.7 % | +299.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.17 s | 2.6 % | +309.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.61 s | 2.4 % | +318.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.47 s | 2.4 % | +326.87 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +335.35 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +335.37 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +335.38 s |
| diarization_load | · diarization.load | 1 | ok | 1.79 s | 0.5 % | +335.38 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.92 s | 3.6 % | +337.17 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +350.09 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +350.10 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +350.10 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +350.15 s |
| queue | · asr.queue_wait | 1 | ok | 350.15 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +350.15 s |
| queue | · asr.queue_wait | 1 | ok | 350.15 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +350.16 s |
| queue | · asr.queue_wait | 1 | ok | 350.15 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +350.16 s |
| queue | · asr.queue_wait | 1 | ok | 350.16 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +350.16 s |
| queue | · asr.queue_wait | 1 | ok | 350.16 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.64 s | 0.2 % | +351.18 s |
| other | notes.generate | 1 | ok | 7.13 s | — | +351.83 s |
| llm_call | · llm.note_write | 1 | ok | 7.01 s | 2.0 % | +351.88 s |

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
| lid.recording | 90.00 s | 6.05 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 5.28 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 5.12 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 5.27 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 5.05 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 5.59 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 5.02 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 5.35 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 5.41 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 5.74 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 5.53 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 5.41 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 6.28 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 5.81 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 6.22 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 5.74 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 5.69 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 6.05 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 5.79 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 5.85 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 5.56 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 6.04 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 8.47 s | 1.199 |
| asr.chunk | faster_whisper | 7.71 s | 8.91 s | 1.155 |
| asr.chunk | faster_whisper | 6.62 s | 8.54 s | 1.289 |
| asr.chunk | faster_whisper | 7.71 s | 8.51 s | 1.104 |
| asr.chunk | faster_whisper | 6.24 s | 8.83 s | 1.416 |
| asr.chunk | faster_whisper | 7.07 s | 9.45 s | 1.337 |
| asr.chunk | faster_whisper | 7.16 s | 8.95 s | 1.249 |
| asr.chunk | faster_whisper | 6.56 s | 9.20 s | 1.403 |
| asr.chunk | faster_whisper | 6.24 s | 8.43 s | 1.353 |
| asr.chunk | faster_whisper | 5.88 s | 8.66 s | 1.471 |
| asr.chunk | faster_whisper | 4.92 s | 8.25 s | 1.675 |
| asr.chunk | faster_whisper | 6.43 s | 7.95 s | 1.237 |
| asr.chunk | faster_whisper | 4.48 s | 8.47 s | 1.893 |
| asr.chunk | faster_whisper | 1.05 s | 6.80 s | 6.464 |
| asr.chunk | faster_whisper | 7.90 s | 9.06 s | 1.147 |
| asr.chunk | faster_whisper | 10.46 s | 9.36 s | 0.895 |
| asr.chunk | faster_whisper | 8.41 s | 9.47 s | 1.125 |
| asr.chunk | faster_whisper | 9.66 s | 10.01 s | 1.037 |
| asr.chunk | faster_whisper | 11.64 s | 9.61 s | 0.825 |
| asr.chunk | faster_whisper | 7.45 s | 9.17 s | 1.231 |
| asr.chunk | faster_whisper | 5.88 s | 8.61 s | 1.463 |
| asr.chunk | faster_whisper | 2.68 s | 8.47 s | 3.156 |

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
| load | ok | 1.79 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 12.92 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.64 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.01 s | 2,071 | 0 | 0 | 409 | — (not_supported) |
| **total** |  | 2 |  |  | 7.65 s | 2,083 | 0 | 0 | 415 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,027,136 B (2.29 GiB) → 3,038,310,400 B (2.83 GiB) |
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

- Top critical-path stages: asr_primary 193.27 s (53.8 %); language_detection 123.85 s (34.5 %); diarization_infer 12.92 s (3.6 %).
- Reprocessing ratio: 0.837.
- Cold loads: vad.model 1.44 s; diarization.load 1.79 s.
- Queue wait: 12.81 s.
- LLM latency share of wall: 2.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
