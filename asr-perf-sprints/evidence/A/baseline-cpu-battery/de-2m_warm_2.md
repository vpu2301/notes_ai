# Diagnostics — recording 91963196-e95d-4a9c-93d6-18ca45e9f268

Run `4e234470-6d68-43d6-a4c0-33168d0c12be` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 91963196-e95d-4a9c-93d6-18ca45e9f268 |
| processing_run_id | 4e234470-6d68-43d6-a4c0-33168d0c12be |
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
| processing_wall_seconds | 345.16 s |
| rtf | 3.031 |
| speedup | 0.330 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.23 s | 0.1 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.22 s |
| other | worker_job | 1 | ok | 334.65 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.25 s | 0.1 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| vad | · vad.speech_runs | 1 | ok | 6.28 s | 1.8 % | +0.30 s |
| language_detection | · lid.recording | 1 | ok | 10.74 s | 3.1 % | +6.58 s |
| language_detection | · lid.run | 1 | ok | 10.01 s | 2.9 % | +17.33 s |
| language_detection | · lid.run | 1 | ok | 9.31 s | 2.7 % | +27.34 s |
| language_detection | · lid.run | 1 | ok | 8.63 s | 2.5 % | +36.65 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 2.7 % | +45.29 s |
| language_detection | · lid.run | 1 | ok | 9.12 s | 2.6 % | +54.51 s |
| language_detection | · lid.run | 1 | ok | 9.24 s | 2.7 % | +63.64 s |
| language_detection | · lid.run | 1 | ok | 9.15 s | 2.7 % | +72.89 s |
| language_detection | · lid.run | 1 | ok | 9.58 s | 2.8 % | +82.04 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 2.6 % | +91.64 s |
| language_detection | · lid.run | 1 | ok | 8.48 s | 2.5 % | +100.66 s |
| language_detection | · lid.run | 1 | ok | 8.92 s | 2.6 % | +109.14 s |
| language_detection | · lid.run | 1 | ok | 9.41 s | 2.7 % | +118.08 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 194.09 s | 56.2 % | +127.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.29 s | 4.4 % | +127.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.75 s | 4.0 % | +142.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.76 s | 5.1 % | +156.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.84 s | 4.3 % | +174.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.59 s | 4.2 % | +189.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.24 s | 4.7 % | +203.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.00 s | 3.8 % | +220.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.28 s | 4.1 % | +233.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.85 s | 4.3 % | +247.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.36 s | 4.2 % | +262.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.28 s | 4.1 % | +276.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.99 s | 4.6 % | +290.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.72 s | 4.3 % | +306.87 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +321.59 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +321.60 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +321.60 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +321.60 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.97 s | 3.8 % | +321.61 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +334.58 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +334.59 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +334.59 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.69 s |
| queue | · asr.queue_wait | 1 | ok | 334.69 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.70 s |
| queue | · asr.queue_wait | 1 | ok | 334.69 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.71 s |
| queue | · asr.queue_wait | 1 | ok | 334.70 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.71 s |
| queue | · asr.queue_wait | 1 | ok | 334.70 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.62 s | 0.2 % | +336.75 s |
| other | notes.generate | 1 | ok | 7.78 s | — | +337.37 s |
| llm_call | · llm.note_write | 1 | ok | 7.66 s | 2.2 % | +337.45 s |

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
| lid.recording | 90.00 s | 10.74 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 10.01 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 9.31 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 8.63 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 9.22 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 9.12 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 9.24 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 9.15 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 9.58 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 9.02 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 8.48 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 8.92 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 9.41 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 15.29 s | 1.732 |
| asr.chunk | faster_whisper | 8.92 s | 13.75 s | 1.541 |
| asr.chunk | faster_whisper | 5.85 s | 17.76 s | 3.035 |
| asr.chunk | faster_whisper | 9.95 s | 14.84 s | 1.491 |
| asr.chunk | faster_whisper | 8.16 s | 14.59 s | 1.789 |
| asr.chunk | faster_whisper | 9.63 s | 16.24 s | 1.687 |
| asr.chunk | faster_whisper | 5.85 s | 12.99 s | 2.221 |
| asr.chunk | faster_whisper | 9.88 s | 14.28 s | 1.445 |
| asr.chunk | faster_whisper | 7.04 s | 14.85 s | 2.111 |
| asr.chunk | faster_whisper | 9.63 s | 14.36 s | 1.492 |
| asr.chunk | faster_whisper | 8.35 s | 14.28 s | 1.711 |
| asr.chunk | faster_whisper | 3.64 s | 15.99 s | 4.389 |
| asr.chunk | faster_whisper | 1.93 s | 14.72 s | 7.623 |

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
| infer | ok | 12.97 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.66 s | 1,820 | 0 | 0 | 293 | — (not_supported) |
| **total** |  | 2 |  |  | 8.28 s | 1,832 | 0 | 0 | 299 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,974,257,152 B (2.77 GiB) → 3,024,367,616 B (2.82 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
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

- Top critical-path stages: asr_primary 194.09 s (56.2 %); language_detection 120.84 s (35.0 %); diarization_infer 12.97 s (3.8 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: 2.4 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
