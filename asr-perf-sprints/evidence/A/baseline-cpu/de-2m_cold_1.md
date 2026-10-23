# Diagnostics — recording a68c3ad8-ef33-4f5b-85cd-e671fe0bcd5c

Run `80f54857-96ba-4863-99b5-4d93df3a8dc8` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | a68c3ad8-ef33-4f5b-85cd-e671fe0bcd5c |
| processing_run_id | 80f54857-96ba-4863-99b5-4d93df3a8dc8 |
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
| processing_wall_seconds | 197.09 s |
| rtf | 1.731 |
| speedup | 0.578 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.14 s | 0.1 % | -0.15 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 177.03 s | — | +12.33 s |
| queue | · asr.queue_wait | 1 | ok | 12.32 s | 6.3 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.32 s | 0.2 % | +12.34 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +12.66 s |
| model_init | · vad.model | 1 | ok | 1.69 s | 0.9 % | +12.66 s |
| vad | · vad.speech_runs | 1 | ok | 3.84 s | 1.9 % | +14.35 s |
| language_detection | · lid.recording | 1 | ok | 5.26 s | 2.7 % | +18.20 s |
| language_detection | · lid.run | 1 | ok | 4.79 s | 2.4 % | +23.46 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 2.6 % | +28.26 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 2.8 % | +33.34 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.5 % | +38.90 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 2.6 % | +43.82 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 2.4 % | +48.91 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.5 % | +53.60 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.5 % | +58.52 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.6 % | +63.38 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 2.5 % | +68.47 s |
| language_detection | · lid.run | 1 | ok | 4.82 s | 2.4 % | +73.30 s |
| language_detection | · lid.run | 1 | ok | 4.56 s | 2.3 % | +78.12 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 95.21 s | 48.3 % | +82.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.41 s | 3.8 % | +82.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.40 s | 3.8 % | +90.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.53 s | 3.8 % | +97.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.52 s | 3.8 % | +105.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.46 s | 3.8 % | +112.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.86 s | 4.0 % | +120.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.43 s | 3.8 % | +127.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.48 s | 3.8 % | +135.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.52 s | 3.8 % | +142.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.73 s | 3.9 % | +150.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.24 s | 4.2 % | +158.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.60 s | 2.8 % | +166.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.99 s | 3.0 % | +171.91 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +177.89 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +177.91 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +177.91 s |
| diarization_load | · diarization.load | 1 | ok | 2.11 s | 1.1 % | +177.91 s |
| diarization_infer | · diarization.infer | 1 | ok | 9.27 s | 4.7 % | +180.02 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +189.29 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +189.30 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +189.30 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +189.36 s |
| queue | · asr.queue_wait | 1 | ok | 189.36 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +189.37 s |
| queue | · asr.queue_wait | 1 | ok | 189.36 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.57 s | 0.3 % | +191.45 s |
| other | notes.generate | 1 | ok | 5.07 s | — | +192.02 s |
| llm_call | · llm.note_write | 1 | ok | 4.99 s | 2.5 % | +192.06 s |

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
| lid.recording | 90.00 s | 5.26 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 4.79 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 5.08 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 5.55 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 4.92 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 5.08 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 4.69 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 4.92 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 4.85 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 5.09 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 4.83 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 4.82 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 4.56 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 7.41 s | 0.840 |
| asr.chunk | faster_whisper | 8.92 s | 7.40 s | 0.829 |
| asr.chunk | faster_whisper | 5.85 s | 7.53 s | 1.286 |
| asr.chunk | faster_whisper | 9.95 s | 7.52 s | 0.756 |
| asr.chunk | faster_whisper | 8.16 s | 7.46 s | 0.915 |
| asr.chunk | faster_whisper | 9.63 s | 7.86 s | 0.816 |
| asr.chunk | faster_whisper | 5.85 s | 7.43 s | 1.270 |
| asr.chunk | faster_whisper | 9.88 s | 7.48 s | 0.757 |
| asr.chunk | faster_whisper | 7.04 s | 7.52 s | 1.068 |
| asr.chunk | faster_whisper | 9.63 s | 7.73 s | 0.803 |
| asr.chunk | faster_whisper | 8.35 s | 8.24 s | 0.987 |
| asr.chunk | faster_whisper | 3.64 s | 5.60 s | 1.537 |
| asr.chunk | faster_whisper | 1.93 s | 5.99 s | 3.099 |

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
| load | ok | 2.11 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 9.27 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.57 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.99 s | 1,820 | 0 | 0 | 292 | — (not_supported) |
| **total** |  | 2 |  |  | 5.56 s | 1,832 | 0 | 0 | 298 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,449,024 B (2.29 GiB) → 2,971,516,928 B (2.77 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.09 → some_avg10=0.71 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,173 B |

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

- Top critical-path stages: asr_primary 95.20 s (48.3 %); language_detection 64.45 s (32.7 %); queue 12.32 s (6.3 %).
- Reprocessing ratio: 0.858.
- Cold loads: vad.model 1.69 s; diarization.load 2.11 s.
- Queue wait: 12.32 s.
- LLM latency share of wall: 2.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
