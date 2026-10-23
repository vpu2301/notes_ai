# Diagnostics — recording 8e0aefb7-40e9-4bc2-a23d-3165f2ffa4d2

Run `1662f2e8-84a8-4dc6-aa57-fdd906a2a435` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 8e0aefb7-40e9-4bc2-a23d-3165f2ffa4d2 |
| processing_run_id | 1662f2e8-84a8-4dc6-aa57-fdd906a2a435 |
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
| processing_wall_seconds | 198.72 s |
| rtf | 1.745 |
| speedup | 0.573 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.12 s | 0.1 % | -0.12 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 190.54 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.18 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.21 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.21 s |
| vad | · vad.speech_runs | 1 | ok | 2.39 s | 1.2 % | +0.21 s |
| language_detection | · lid.recording | 1 | ok | 5.99 s | 3.0 % | +2.60 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 2.9 % | +8.61 s |
| language_detection | · lid.run | 1 | ok | 5.19 s | 2.6 % | +14.43 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.4 % | +19.62 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 2.8 % | +24.47 s |
| language_detection | · lid.run | 1 | ok | 4.91 s | 2.5 % | +29.95 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.6 % | +34.87 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 3.0 % | +39.96 s |
| language_detection | · lid.run | 1 | ok | 5.30 s | 2.7 % | +46.00 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 2.8 % | +51.30 s |
| language_detection | · lid.run | 1 | ok | 5.38 s | 2.7 % | +56.83 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 2.9 % | +62.21 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 2.6 % | +67.89 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 110.18 s | 55.4 % | +73.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.96 s | 4.0 % | +73.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.20 s | 4.1 % | +81.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.68 s | 3.9 % | +89.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.74 s | 4.4 % | +96.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.70 s | 4.4 % | +105.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.91 s | 4.5 % | +114.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.45 s | 4.3 % | +123.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.78 s | 4.4 % | +131.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 4.9 % | +140.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.79 s | 4.4 % | +150.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.20 s | 4.6 % | +159.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.47 s | 3.8 % | +168.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.58 s | 3.8 % | +175.74 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +183.33 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +183.33 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +183.33 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +183.33 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.16 s | 3.6 % | +183.33 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +190.50 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +190.50 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +190.50 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +190.57 s |
| queue | · asr.queue_wait | 1 | ok | 190.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +190.57 s |
| queue | · asr.queue_wait | 1 | ok | 190.57 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | error | 0.48 s | 0.2 % | +191.76 s |
| llm_call | llm.provider_probe | 1 | ok | 0.88 s | 0.4 % | +193.25 s |
| other | notes.generate | 1 | ok | 4.59 s | — | +194.13 s |
| llm_call | · llm.note_write | 1 | ok | 4.50 s | 2.3 % | +194.18 s |

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
| lid.recording | 90.00 s | 5.99 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 5.81 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 5.19 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 4.85 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 5.48 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 4.91 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 5.09 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 6.03 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 5.30 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 5.53 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 5.38 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 5.67 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 5.26 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 7.96 s | 0.901 |
| asr.chunk | faster_whisper | 8.92 s | 8.20 s | 0.919 |
| asr.chunk | faster_whisper | 5.85 s | 7.68 s | 1.312 |
| asr.chunk | faster_whisper | 9.95 s | 8.74 s | 0.879 |
| asr.chunk | faster_whisper | 8.16 s | 8.70 s | 1.066 |
| asr.chunk | faster_whisper | 9.63 s | 8.91 s | 0.925 |
| asr.chunk | faster_whisper | 5.85 s | 8.45 s | 1.444 |
| asr.chunk | faster_whisper | 9.88 s | 8.78 s | 0.888 |
| asr.chunk | faster_whisper | 7.04 s | 9.68 s | 1.376 |
| asr.chunk | faster_whisper | 9.63 s | 8.79 s | 0.913 |
| asr.chunk | faster_whisper | 8.35 s | 9.20 s | 1.102 |
| asr.chunk | faster_whisper | 3.64 s | 7.47 s | 2.049 |
| asr.chunk | faster_whisper | 1.93 s | 7.58 s | 3.927 |

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
| infer | ok | 7.16 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | error | — (not_applicable) | 0.48 s | 7* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 2 | ok | — (not_applicable) | 0.88 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.50 s | 1,820 | 0 | 0 | 324 | — (not_supported) |
| **total** |  | 3 |  |  | 5.86 s | 1,839 | 0 | 0 | 330 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again; estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,393,104,384 B (2.23 GiB) → 3,058,388,992 B (2.85 GiB) |
| swap used | 20,832,256 B (0.02 GiB) → 20,881,408 B (0.02 GiB) |
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
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - note_write (attempt 1): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 1): `model_load_seconds` (not_applicable)
  - note_write (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
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

- Top critical-path stages: asr_primary 110.18 s (55.4 %); language_detection 70.50 s (35.5 %); diarization_infer 7.16 s (3.6 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 3.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
