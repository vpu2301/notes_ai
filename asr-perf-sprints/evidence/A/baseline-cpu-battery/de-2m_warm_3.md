# Diagnostics — recording e8e34fbf-2fdd-43ac-94dc-c34e2ce2758e

Run `b90a9a93-a06c-4254-81ca-26673dec1fb2` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | e8e34fbf-2fdd-43ac-94dc-c34e2ce2758e |
| processing_run_id | b90a9a93-a06c-4254-81ca-26673dec1fb2 |
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
| processing_wall_seconds | 349.67 s |
| rtf | 3.071 |
| speedup | 0.326 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.18 s | 0.1 % | -0.19 s |
| capture_input | asr.submit.probe | 1 | ok | 0.12 s | 0.0 % | -0.17 s |
| other | worker_job | 1 | ok | 342.10 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.21 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| vad | · vad.speech_runs | 1 | ok | 4.26 s | 1.2 % | +0.24 s |
| language_detection | · lid.recording | 1 | ok | 9.82 s | 2.8 % | +4.51 s |
| language_detection | · lid.run | 1 | ok | 12.57 s | 3.6 % | +14.34 s |
| language_detection | · lid.run | 1 | ok | 12.28 s | 3.5 % | +26.92 s |
| language_detection | · lid.run | 1 | ok | 10.76 s | 3.1 % | +39.20 s |
| language_detection | · lid.run | 1 | ok | 9.34 s | 2.7 % | +49.97 s |
| language_detection | · lid.run | 1 | ok | 9.24 s | 2.6 % | +59.31 s |
| language_detection | · lid.run | 1 | ok | 9.17 s | 2.6 % | +68.55 s |
| language_detection | · lid.run | 1 | ok | 8.90 s | 2.5 % | +77.73 s |
| language_detection | · lid.run | 1 | ok | 9.33 s | 2.7 % | +86.63 s |
| language_detection | · lid.run | 1 | ok | 9.39 s | 2.7 % | +95.97 s |
| language_detection | · lid.run | 1 | ok | 9.57 s | 2.7 % | +105.37 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | 2.6 % | +114.94 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 2.8 % | +123.94 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 195.15 s | 55.8 % | +133.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.29 s | 4.4 % | +133.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.88 s | 4.5 % | +148.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.79 s | 4.5 % | +164.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.11 s | 4.6 % | +180.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.12 s | 4.0 % | +196.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.37 s | 5.0 % | +210.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.64 s | 4.5 % | +228.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.06 s | 4.6 % | +243.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.48 s | 4.4 % | +260.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.67 s | 4.5 % | +275.48 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.15 s | 4.3 % | +291.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.54 s | 3.3 % | +306.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.94 s | 3.1 % | +317.87 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +328.81 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +328.81 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +328.82 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +328.82 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.20 s | 3.8 % | +328.82 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +342.02 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +342.03 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +342.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.13 s |
| queue | · asr.queue_wait | 1 | ok | 342.13 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.14 s |
| queue | · asr.queue_wait | 1 | ok | 342.13 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.14 s |
| queue | · asr.queue_wait | 1 | ok | 342.14 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.15 s |
| queue | · asr.queue_wait | 1 | ok | 342.14 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +342.15 s |
| queue | · asr.queue_wait | 1 | ok | 342.15 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.89 s | 0.3 % | +343.32 s |
| other | notes.generate | 1 | ok | 5.46 s | — | +344.21 s |
| llm_call | · llm.note_write | 1 | ok | 5.24 s | 1.5 % | +344.38 s |

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
| lid.recording | 90.00 s | 9.82 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 12.57 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 12.28 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 10.76 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 9.34 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 9.24 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 9.17 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 8.90 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 9.33 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 9.39 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 9.57 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 9.00 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 9.71 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 15.29 s | 1.732 |
| asr.chunk | faster_whisper | 8.92 s | 15.88 s | 1.779 |
| asr.chunk | faster_whisper | 5.85 s | 15.78 s | 2.697 |
| asr.chunk | faster_whisper | 9.95 s | 16.11 s | 1.619 |
| asr.chunk | faster_whisper | 8.16 s | 14.12 s | 1.731 |
| asr.chunk | faster_whisper | 9.63 s | 17.37 s | 1.804 |
| asr.chunk | faster_whisper | 5.85 s | 15.64 s | 2.672 |
| asr.chunk | faster_whisper | 9.88 s | 16.05 s | 1.624 |
| asr.chunk | faster_whisper | 7.04 s | 15.48 s | 2.200 |
| asr.chunk | faster_whisper | 9.63 s | 15.67 s | 1.628 |
| asr.chunk | faster_whisper | 8.35 s | 15.15 s | 1.815 |
| asr.chunk | faster_whisper | 3.64 s | 11.54 s | 3.166 |
| asr.chunk | faster_whisper | 1.93 s | 10.94 s | 5.666 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 13.20 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.89 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.24 s | 1,820 | 0 | 0 | 305 | — (not_supported) |
| **total** |  | 2 |  |  | 6.13 s | 1,832 | 0 | 0 | 311 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,024,732,160 B (2.82 GiB) → 3,020,075,008 B (2.81 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,595 B |

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

- Top critical-path stages: asr_primary 195.15 s (55.8 %); language_detection 129.08 s (36.9 %); diarization_infer 13.20 s (3.8 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
