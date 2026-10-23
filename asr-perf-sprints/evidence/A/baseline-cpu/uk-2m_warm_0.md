# Diagnostics — recording caede707-9d6d-4171-a4b7-6cab4fd9ac06

Run `44b11fcd-99ad-45bb-9333-8ba2db80591c` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | caede707-9d6d-4171-a4b7-6cab4fd9ac06 |
| processing_run_id | 44b11fcd-99ad-45bb-9333-8ba2db80591c |
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
| processing_wall_seconds | 191.93 s |
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
| upload | asr.submit.upload | 1 | ok | 0.14 s | 0.1 % | -0.15 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 181.02 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.14 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.17 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.17 s |
| vad | · vad.speech_runs | 1 | ok | 2.04 s | 1.1 % | +0.17 s |
| language_detection | · lid.recording | 1 | ok | 5.81 s | 3.0 % | +2.21 s |
| language_detection | · lid.run | 1 | ok | 5.16 s | 2.7 % | +8.02 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 2.8 % | +13.19 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 2.9 % | +18.49 s |
| language_detection | · lid.run | 1 | ok | 5.18 s | 2.7 % | +24.00 s |
| language_detection | · lid.run | 1 | ok | 4.91 s | 2.6 % | +29.19 s |
| language_detection | · lid.run | 1 | ok | 4.99 s | 2.6 % | +34.10 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 2.6 % | +39.09 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 2.6 % | +44.15 s |
| language_detection | · lid.run | 1 | ok | 5.04 s | 2.6 % | +49.17 s |
| language_detection | · lid.run | 1 | ok | 5.14 s | 2.7 % | +54.21 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.7 % | +59.35 s |
| language_detection | · lid.run | 1 | ok | 5.01 s | 2.6 % | +64.44 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 104.64 s | 54.5 % | +69.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.39 s | 4.4 % | +69.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.19 s | 4.8 % | +77.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.13 s | 4.2 % | +87.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.03 s | 4.7 % | +95.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.22 s | 4.3 % | +104.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.90 s | 4.6 % | +112.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.27 s | 4.3 % | +121.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.34 s | 4.3 % | +129.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.42 s | 5.4 % | +137.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.75 s | 4.6 % | +148.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.59 s | 5.5 % | +157.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.36 s | 3.3 % | +167.79 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +174.15 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +174.15 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +174.15 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +174.15 s |
| diarization_infer | · diarization.infer | 1 | ok | 6.90 s | 3.6 % | +174.16 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +181.06 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +181.06 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +181.06 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +181.11 s |
| queue | · asr.queue_wait | 1 | ok | 181.10 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +181.11 s |
| queue | · asr.queue_wait | 1 | ok | 181.11 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.73 s | 0.4 % | +182.05 s |
| other | notes.generate | 1 | ok | 9.15 s | — | +182.78 s |
| llm_call | · llm.note_write | 1 | ok | 9.06 s | 4.7 % | +182.83 s |

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
| lid.recording | 90.00 s | 5.81 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 5.16 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 5.29 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 5.51 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 5.18 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 4.91 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 4.99 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 5.06 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 5.02 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 5.04 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 5.14 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 5.09 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 5.01 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 8.39 s | 1.126 |
| asr.chunk | faster_whisper | 9.85 s | 9.19 s | 0.933 |
| asr.chunk | faster_whisper | 7.48 s | 8.13 s | 1.086 |
| asr.chunk | faster_whisper | 10.49 s | 9.03 s | 0.861 |
| asr.chunk | faster_whisper | 7.13 s | 8.22 s | 1.153 |
| asr.chunk | faster_whisper | 7.71 s | 8.90 s | 1.155 |
| asr.chunk | faster_whisper | 7.58 s | 8.27 s | 1.091 |
| asr.chunk | faster_whisper | 6.75 s | 8.34 s | 1.237 |
| asr.chunk | faster_whisper | 12.28 s | 10.42 s | 0.848 |
| asr.chunk | faster_whisper | 9.82 s | 8.75 s | 0.891 |
| asr.chunk | faster_whisper | 14.24 s | 10.59 s | 0.744 |
| asr.chunk | faster_whisper | 2.64 s | 6.36 s | 2.410 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 6.90 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.73 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 9.06 s | 2,024 | 0 | 0 | 502 | — (not_supported) |
| **total** |  | 2 |  |  | 9.80 s | 2,036 | 0 | 0 | 508 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,102,818,304 B (2.89 GiB) → 3,084,464,128 B (2.87 GiB) |
| swap used | 72,998,912 B (0.07 GiB) → 72,986,624 B (0.07 GiB) |
| memory pressure | some_avg10=0.03 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,587 B |

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

- Top critical-path stages: asr_primary 104.70 s (54.5 %); language_detection 67.22 s (35.0 %); llm_call 9.80 s (5.1 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 5.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
