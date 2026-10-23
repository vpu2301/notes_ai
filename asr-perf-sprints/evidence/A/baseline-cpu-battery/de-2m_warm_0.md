# Diagnostics — recording 3baa6b80-319b-4977-b926-47a4b04254d8

Run `988e351d-640f-4244-b15b-9e7ea768dae4` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 3baa6b80-319b-4977-b926-47a4b04254d8 |
| processing_run_id | 988e351d-640f-4244-b15b-9e7ea768dae4 |
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
| processing_wall_seconds | 329.40 s |
| rtf | 2.893 |
| speedup | 0.346 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.83 s | 0.3 % | -0.85 s |
| capture_input | asr.submit.probe | 1 | ok | 0.37 s | 0.1 % | -0.83 s |
| other | worker_job | 1 | ok | 321.52 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.07 s | 0.3 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +1.11 s |
| model_init | · vad.model | 1 | ok | 2.79 s | 0.8 % | +1.11 s |
| vad | · vad.speech_runs | 1 | ok | 2.80 s | 0.9 % | +3.90 s |
| language_detection | · lid.recording | 1 | ok | 9.67 s | 2.9 % | +6.70 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 2.7 % | +16.38 s |
| language_detection | · lid.run | 1 | ok | 8.71 s | 2.6 % | +25.32 s |
| language_detection | · lid.run | 1 | ok | 8.52 s | 2.6 % | +34.03 s |
| language_detection | · lid.run | 1 | ok | 8.62 s | 2.6 % | +42.55 s |
| language_detection | · lid.run | 1 | ok | 8.92 s | 2.7 % | +51.19 s |
| language_detection | · lid.run | 1 | ok | 8.31 s | 2.5 % | +60.11 s |
| language_detection | · lid.run | 1 | ok | 8.84 s | 2.7 % | +68.43 s |
| language_detection | · lid.run | 1 | ok | 8.21 s | 2.5 % | +77.28 s |
| language_detection | · lid.run | 1 | ok | 8.72 s | 2.6 % | +85.49 s |
| language_detection | · lid.run | 1 | ok | 8.44 s | 2.6 % | +94.21 s |
| language_detection | · lid.run | 1 | ok | 8.48 s | 2.6 % | +102.66 s |
| language_detection | · lid.run | 1 | ok | 8.69 s | 2.6 % | +111.14 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 185.71 s | 56.4 % | +119.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.62 s | 4.7 % | +119.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.65 s | 3.8 % | +135.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.50 s | 3.8 % | +148.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.41 s | 4.1 % | +160.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.73 s | 4.2 % | +174.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.64 s | 4.1 % | +187.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.38 s | 4.7 % | +201.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.26 s | 4.6 % | +216.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.78 s | 6.0 % | +232.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.25 s | 4.6 % | +251.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.17 s | 4.3 % | +267.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.17 s | 4.0 % | +281.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.05 s | 3.4 % | +294.48 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +305.53 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +305.56 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +305.56 s |
| diarization_load | · diarization.load | 1 | ok | 3.70 s | 1.1 % | +305.56 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.20 s | 3.7 % | +309.26 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +321.47 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +321.48 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +321.48 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +321.58 s |
| queue | · asr.queue_wait | 1 | ok | 321.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +321.59 s |
| queue | · asr.queue_wait | 1 | ok | 321.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +321.59 s |
| queue | · asr.queue_wait | 1 | ok | 321.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +321.59 s |
| queue | · asr.queue_wait | 1 | ok | 321.59 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.62 s | 0.2 % | +323.80 s |
| other | notes.generate | 1 | ok | 4.97 s | — | +324.43 s |
| llm_call | · llm.note_write | 1 | ok | 4.67 s | 1.4 % | +324.64 s |

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
| lid.recording | 90.00 s | 9.67 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 8.93 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 8.71 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 8.52 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 8.62 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 8.92 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 8.31 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 8.84 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 8.21 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 8.72 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 8.44 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 8.48 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 8.69 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 15.62 s | 1.769 |
| asr.chunk | faster_whisper | 8.92 s | 12.65 s | 1.418 |
| asr.chunk | faster_whisper | 5.85 s | 12.50 s | 2.136 |
| asr.chunk | faster_whisper | 9.95 s | 13.41 s | 1.348 |
| asr.chunk | faster_whisper | 8.16 s | 13.73 s | 1.683 |
| asr.chunk | faster_whisper | 9.63 s | 13.64 s | 1.416 |
| asr.chunk | faster_whisper | 5.85 s | 15.38 s | 2.628 |
| asr.chunk | faster_whisper | 9.88 s | 15.26 s | 1.544 |
| asr.chunk | faster_whisper | 7.04 s | 19.78 s | 2.812 |
| asr.chunk | faster_whisper | 9.63 s | 15.25 s | 1.584 |
| asr.chunk | faster_whisper | 8.35 s | 14.17 s | 1.697 |
| asr.chunk | faster_whisper | 3.64 s | 13.17 s | 3.615 |
| asr.chunk | faster_whisper | 1.93 s | 11.05 s | 5.725 |

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
| load | ok | 3.70 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 12.20 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.67 s | 1,820 | 0 | 0 | 292 | — (not_supported) |
| **total** |  | 2 |  |  | 5.29 s | 1,832 | 0 | 0 | 298 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,454,900,736 B (2.29 GiB) → 2,976,542,720 B (2.77 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=1.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,175 B |

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

- Top critical-path stages: asr_primary 185.70 s (56.4 %); language_detection 113.07 s (34.3 %); diarization_infer 12.21 s (3.7 %).
- Reprocessing ratio: 0.858.
- Cold loads: vad.model 2.79 s; diarization.load 3.70 s.
- Queue wait: 0.02 s.
- LLM latency share of wall: 1.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
