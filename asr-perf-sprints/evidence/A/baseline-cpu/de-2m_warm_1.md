# Diagnostics — recording 049cd9d8-ccad-4a7a-b438-b28ad5d64602

Run `a3698415-2458-48dd-b54c-e467e8ae6f3d` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 049cd9d8-ccad-4a7a-b438-b28ad5d64602 |
| processing_run_id | a3698415-2458-48dd-b54c-e467e8ae6f3d |
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
| processing_wall_seconds | 231.88 s |
| rtf | 2.036 |
| speedup | 0.491 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.10 s | 0.0 % | -0.11 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.10 s |
| other | worker_job | 1 | ok | 225.79 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.13 s | 0.1 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.14 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.14 s |
| vad | · vad.speech_runs | 1 | ok | 2.15 s | 0.9 % | +0.15 s |
| language_detection | · lid.recording | 1 | ok | 6.78 s | 2.9 % | +2.29 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 2.4 % | +9.08 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 2.6 % | +14.75 s |
| language_detection | · lid.run | 1 | ok | 5.61 s | 2.4 % | +20.79 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 2.5 % | +26.41 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 2.6 % | +32.15 s |
| language_detection | · lid.run | 1 | ok | 6.46 s | 2.8 % | +38.12 s |
| language_detection | · lid.run | 1 | ok | 5.99 s | 2.6 % | +44.58 s |
| language_detection | · lid.run | 1 | ok | 6.45 s | 2.8 % | +50.58 s |
| language_detection | · lid.run | 1 | ok | 6.82 s | 2.9 % | +57.04 s |
| language_detection | · lid.run | 1 | ok | 6.11 s | 2.6 % | +63.86 s |
| language_detection | · lid.run | 1 | ok | 6.59 s | 2.8 % | +69.97 s |
| language_detection | · lid.run | 1 | ok | 7.20 s | 3.1 % | +76.58 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 129.24 s | 55.7 % | +83.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.97 s | 3.9 % | +83.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.48 s | 4.1 % | +92.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.05 s | 3.9 % | +102.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.61 s | 5.0 % | +111.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.96 s | 4.7 % | +122.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.09 s | 4.4 % | +133.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.23 s | 3.5 % | +143.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.33 s | 4.5 % | +152.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.89 s | 4.7 % | +162.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.27 s | 4.4 % | +173.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.32 s | 4.5 % | +183.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.46 s | 4.1 % | +193.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.47 s | 4.1 % | +203.47 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +212.95 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +212.96 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +212.96 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +212.97 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.68 s | 5.5 % | +212.97 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +225.65 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +225.66 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +225.66 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +225.75 s |
| queue | · asr.queue_wait | 1 | ok | 225.74 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +225.75 s |
| queue | · asr.queue_wait | 1 | ok | 225.75 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +225.76 s |
| queue | · asr.queue_wait | 1 | ok | 225.75 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.65 s | 0.3 % | +227.07 s |
| other | notes.generate | 1 | ok | 4.16 s | — | +227.72 s |
| llm_call | · llm.note_write | 1 | ok | 4.09 s | 1.8 % | +227.75 s |

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
| lid.recording | 90.00 s | 6.78 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 5.67 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 6.03 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 5.61 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 5.74 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 5.97 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 6.46 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 5.99 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 6.45 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 6.82 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 6.11 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 6.59 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 7.20 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 8.97 s | 1.016 |
| asr.chunk | faster_whisper | 8.92 s | 9.48 s | 1.062 |
| asr.chunk | faster_whisper | 5.85 s | 9.05 s | 1.546 |
| asr.chunk | faster_whisper | 9.95 s | 11.61 s | 1.167 |
| asr.chunk | faster_whisper | 8.16 s | 10.96 s | 1.344 |
| asr.chunk | faster_whisper | 9.63 s | 10.09 s | 1.048 |
| asr.chunk | faster_whisper | 5.85 s | 8.23 s | 1.406 |
| asr.chunk | faster_whisper | 9.88 s | 10.33 s | 1.045 |
| asr.chunk | faster_whisper | 7.04 s | 10.89 s | 1.548 |
| asr.chunk | faster_whisper | 9.63 s | 10.27 s | 1.067 |
| asr.chunk | faster_whisper | 8.35 s | 10.32 s | 1.236 |
| asr.chunk | faster_whisper | 3.64 s | 9.46 s | 2.597 |
| asr.chunk | faster_whisper | 1.93 s | 9.46 s | 4.901 |

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
| infer | ok | 12.68 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.65 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.09 s | 1,820 | 0 | 0 | 295 | — (not_supported) |
| **total** |  | 2 |  |  | 4.74 s | 1,832 | 0 | 0 | 301 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,058,790,400 B (2.85 GiB) → 2,410,188,800 B (2.24 GiB) |
| swap used | 20,881,408 B (0.02 GiB) → 21,438,464 B (0.02 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,594 B |

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

- Top critical-path stages: asr_primary 129.17 s (55.7 %); language_detection 81.43 s (35.1 %); diarization_infer 12.68 s (5.5 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
