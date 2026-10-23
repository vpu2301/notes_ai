# Diagnostics — recording 2c0c3ce0-bb5f-424a-bb1c-cb000d7a9727

Run `20a94948-467a-49de-9ad7-eb76a15b8ad9` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 2c0c3ce0-bb5f-424a-bb1c-cb000d7a9727 |
| processing_run_id | 20a94948-467a-49de-9ad7-eb76a15b8ad9 |
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
| audio duration | 114.00 s |
| processing_wall_seconds | 377.08 s |
| rtf | 3.308 |
| speedup | 0.302 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.18 s | 0.0 % | -0.19 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.17 s |
| other | worker_job | 1 | ok | 338.65 s | — | +28.84 s |
| queue | · asr.queue_wait | 1 | ok | 28.83 s | 7.6 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.62 s | 0.2 % | +28.85 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +29.47 s |
| model_init | · vad.model | 1 | ok | 2.59 s | 0.7 % | +29.47 s |
| vad | · vad.speech_runs | 1 | ok | 2.78 s | 0.7 % | +32.06 s |
| language_detection | · lid.recording | 1 | ok | 8.64 s | 2.3 % | +34.84 s |
| language_detection | · lid.run | 1 | ok | 9.19 s | 2.4 % | +43.48 s |
| language_detection | · lid.run | 1 | ok | 8.77 s | 2.3 % | +52.68 s |
| language_detection | · lid.run | 1 | ok | 8.54 s | 2.3 % | +61.46 s |
| language_detection | · lid.run | 1 | ok | 8.45 s | 2.2 % | +70.00 s |
| language_detection | · lid.run | 1 | ok | 9.23 s | 2.4 % | +78.45 s |
| language_detection | · lid.run | 1 | ok | 8.30 s | 2.2 % | +87.69 s |
| language_detection | · lid.run | 1 | ok | 9.06 s | 2.4 % | +95.99 s |
| language_detection | · lid.run | 1 | ok | 10.96 s | 2.9 % | +105.06 s |
| language_detection | · lid.run | 1 | ok | 9.60 s | 2.5 % | +116.05 s |
| language_detection | · lid.run | 1 | ok | 8.48 s | 2.2 % | +125.66 s |
| language_detection | · lid.run | 1 | ok | 11.57 s | 3.1 % | +134.15 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 2.4 % | +145.73 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 196.41 s | 52.1 % | +154.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.31 s | 4.1 % | +154.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.70 s | 4.2 % | +170.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.33 s | 4.6 % | +185.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.96 s | 4.5 % | +203.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.26 s | 4.3 % | +220.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.91 s | 5.0 % | +236.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.43 s | 4.9 % | +255.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.23 s | 3.8 % | +273.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.90 s | 4.5 % | +288.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.13 s | 4.3 % | +304.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.84 s | 5.0 % | +321.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.32 s | 3.0 % | +339.93 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +351.25 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +351.28 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +351.28 s |
| diarization_load | · diarization.load | 1 | ok | 3.39 s | 0.9 % | +351.29 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.76 s | 3.4 % | +354.67 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +367.43 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +367.43 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +367.43 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +367.50 s |
| queue | · asr.queue_wait | 1 | ok | 367.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +367.51 s |
| queue | · asr.queue_wait | 1 | ok | 367.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +367.51 s |
| queue | · asr.queue_wait | 1 | ok | 367.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +367.52 s |
| queue | · asr.queue_wait | 1 | ok | 367.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +367.52 s |
| queue | · asr.queue_wait | 1 | ok | 367.52 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.84 s | 0.2 % | +368.81 s |
| other | notes.generate | 1 | ok | 7.43 s | — | +369.65 s |
| llm_call | · llm.note_write | 1 | ok | 7.27 s | 1.9 % | +369.73 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 103.43 s | 12 | 2.64 s | 7.64 s | 14.24 s |

### Language checks

Language checks: 13.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 8.64 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 9.19 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 8.77 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 8.54 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 8.45 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 9.23 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 8.30 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 9.06 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 10.96 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 9.60 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 8.48 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 11.57 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 9.11 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 15.31 s | 2.054 |
| asr.chunk | faster_whisper | 9.85 s | 15.70 s | 1.594 |
| asr.chunk | faster_whisper | 7.48 s | 17.33 s | 2.315 |
| asr.chunk | faster_whisper | 10.49 s | 16.96 s | 1.617 |
| asr.chunk | faster_whisper | 7.13 s | 16.25 s | 2.279 |
| asr.chunk | faster_whisper | 7.71 s | 18.91 s | 2.453 |
| asr.chunk | faster_whisper | 7.58 s | 18.42 s | 2.431 |
| asr.chunk | faster_whisper | 6.75 s | 14.23 s | 2.109 |
| asr.chunk | faster_whisper | 12.28 s | 16.90 s | 1.376 |
| asr.chunk | faster_whisper | 9.82 s | 16.13 s | 1.642 |
| asr.chunk | faster_whisper | 14.24 s | 18.84 s | 1.324 |
| asr.chunk | faster_whisper | 2.64 s | 11.32 s | 4.288 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 103.43 s |
| audio duration | 114.00 s |
| reprocessing ratio | 0.907 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.39 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 12.76 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.84 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.27 s | 2,024 | 0 | 0 | 484 | — (not_supported) |
| **total** |  | 2 |  |  | 8.11 s | 2,036 | 0 | 0 | 490 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,580,096 B (2.29 GiB) → 3,030,618,112 B (2.82 GiB) |
| swap used | 1,422,188,544 B (1.32 GiB) → 1,418,887,168 B (1.32 GiB) |
| memory pressure | some_avg10=0.13 → some_avg10=0.35 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,171 B |

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

- Top critical-path stages: asr_primary 196.41 s (52.1 %); language_detection 119.91 s (31.8 %); queue 28.83 s (7.6 %).
- Reprocessing ratio: 0.907.
- Cold loads: vad.model 2.59 s; diarization.load 3.39 s.
- Queue wait: 28.83 s.
- LLM latency share of wall: 2.2 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
