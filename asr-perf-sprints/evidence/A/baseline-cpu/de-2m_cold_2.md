# Diagnostics — recording 82a35c44-dcea-4a83-aa40-b9b7fda961e5

Run `c3601d3d-877c-49b4-af41-5f1fb4bac01c` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 82a35c44-dcea-4a83-aa40-b9b7fda961e5 |
| processing_run_id | c3601d3d-877c-49b4-af41-5f1fb4bac01c |
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
| audio duration | 113.87 s |
| processing_wall_seconds | 191.71 s |
| rtf | 1.684 |
| speedup | 0.594 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.1 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 169.55 s | — | +13.68 s |
| queue | · asr.queue_wait | 1 | ok | 13.67 s | 7.1 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.64 s | 0.3 % | +13.69 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +14.33 s |
| model_init | · vad.model | 1 | ok | 1.79 s | 0.9 % | +14.33 s |
| vad | · vad.speech_runs | 1 | ok | 3.50 s | 1.8 % | +16.12 s |
| language_detection | · lid.recording | 1 | ok | 5.75 s | 3.0 % | +19.62 s |
| language_detection | · lid.run | 1 | ok | 4.70 s | 2.5 % | +25.37 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 2.5 % | +30.08 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 2.5 % | +34.86 s |
| language_detection | · lid.run | 1 | ok | 4.62 s | 2.4 % | +39.64 s |
| language_detection | · lid.run | 1 | ok | 4.51 s | 2.4 % | +44.26 s |
| language_detection | · lid.run | 1 | ok | 4.54 s | 2.4 % | +48.78 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 2.4 % | +53.32 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 2.4 % | +58.01 s |
| language_detection | · lid.run | 1 | ok | 4.52 s | 2.4 % | +62.58 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 2.4 % | +67.10 s |
| language_detection | · lid.run | 1 | ok | 4.64 s | 2.4 % | +71.71 s |
| language_detection | · lid.run | 1 | ok | 5.22 s | 2.7 % | +76.35 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 91.12 s | 47.5 % | +81.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.68 s | 4.0 % | +81.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.75 s | 4.0 % | +89.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.92 s | 3.6 % | +97.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.49 s | 3.9 % | +103.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.38 s | 3.8 % | +111.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.25 s | 3.8 % | +118.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.70 s | 3.5 % | +126.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.28 s | 3.8 % | +132.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.16 s | 3.7 % | +140.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.39 s | 3.9 % | +147.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.10 s | 3.7 % | +154.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.58 s | 2.9 % | +161.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.41 s | 2.8 % | +167.28 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +172.70 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +172.72 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +172.72 s |
| diarization_load | · diarization.load | 1 | ok | 1.98 s | 1.0 % | +172.72 s |
| diarization_infer | · diarization.infer | 1 | ok | 8.51 s | 4.4 % | +174.70 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +183.21 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +183.21 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +183.21 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +183.24 s |
| queue | · asr.queue_wait | 1 | ok | 183.23 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +183.24 s |
| queue | · asr.queue_wait | 1 | ok | 183.23 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 1.07 s | 0.6 % | +185.09 s |
| other | notes.generate | 1 | ok | 5.54 s | — | +186.17 s |
| llm_call | · llm.note_write | 1 | ok | 5.44 s | 2.8 % | +186.22 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 97.66 s | 13 | 1.93 s | 8.35 s | 9.95 s |

### Language checks

Language checks: 13.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 5.75 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 4.70 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 4.78 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 4.77 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 4.62 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 4.51 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 4.54 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 4.68 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 4.57 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 4.52 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 4.61 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 4.64 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 5.22 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 7.68 s | 0.870 |
| asr.chunk | faster_whisper | 8.92 s | 7.75 s | 0.869 |
| asr.chunk | faster_whisper | 5.85 s | 6.92 s | 1.183 |
| asr.chunk | faster_whisper | 9.95 s | 7.48 s | 0.752 |
| asr.chunk | faster_whisper | 8.16 s | 7.38 s | 0.905 |
| asr.chunk | faster_whisper | 9.63 s | 7.25 s | 0.753 |
| asr.chunk | faster_whisper | 5.85 s | 6.70 s | 1.145 |
| asr.chunk | faster_whisper | 9.88 s | 7.28 s | 0.737 |
| asr.chunk | faster_whisper | 7.04 s | 7.16 s | 1.017 |
| asr.chunk | faster_whisper | 9.63 s | 7.39 s | 0.767 |
| asr.chunk | faster_whisper | 8.35 s | 7.10 s | 0.850 |
| asr.chunk | faster_whisper | 3.64 s | 5.58 s | 1.531 |
| asr.chunk | faster_whisper | 1.93 s | 5.41 s | 2.804 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 97.66 s |
| audio duration | 113.87 s |
| reprocessing ratio | 0.858 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 1.98 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 8.51 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.07 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.44 s | 1,820 | 0 | 0 | 371 | — (not_supported) |
| **total** |  | 2 |  |  | 6.52 s | 1,832 | 0 | 0 | 377 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,452,668,416 B (2.28 GiB) → 3,024,232,448 B (2.82 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.04 → some_avg10=0.40 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,167 B |

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

- Top critical-path stages: asr_primary 91.12 s (47.5 %); language_detection 61.93 s (32.3 %); queue 13.67 s (7.1 %).
- Reprocessing ratio: 0.858.
- Cold loads: vad.model 1.79 s; diarization.load 1.98 s.
- Queue wait: 13.67 s.
- LLM latency share of wall: 3.4 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
