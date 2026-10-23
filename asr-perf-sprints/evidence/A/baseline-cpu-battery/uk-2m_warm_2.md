# Diagnostics — recording 899159f0-409e-4538-8bae-46348b121156

Run `5439b361-cfa4-4655-b878-e4d051157b34` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 899159f0-409e-4538-8bae-46348b121156 |
| processing_run_id | 5439b361-cfa4-4655-b878-e4d051157b34 |
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
| processing_wall_seconds | 336.01 s |
| rtf | 2.947 |
| speedup | 0.339 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.0 % | -0.17 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 325.83 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.20 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.22 s |
| vad | · vad.speech_runs | 1 | ok | 4.50 s | 1.3 % | +0.22 s |
| language_detection | · lid.recording | 1 | ok | 8.84 s | 2.6 % | +4.73 s |
| language_detection | · lid.run | 1 | ok | 9.72 s | 2.9 % | +13.58 s |
| language_detection | · lid.run | 1 | ok | 9.39 s | 2.8 % | +23.30 s |
| language_detection | · lid.run | 1 | ok | 9.01 s | 2.7 % | +32.69 s |
| language_detection | · lid.run | 1 | ok | 9.70 s | 2.9 % | +41.71 s |
| language_detection | · lid.run | 1 | ok | 11.06 s | 3.3 % | +51.41 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 2.7 % | +62.48 s |
| language_detection | · lid.run | 1 | ok | 9.09 s | 2.7 % | +71.51 s |
| language_detection | · lid.run | 1 | ok | 9.53 s | 2.8 % | +80.60 s |
| language_detection | · lid.run | 1 | ok | 9.21 s | 2.7 % | +90.13 s |
| language_detection | · lid.run | 1 | ok | 8.32 s | 2.5 % | +99.35 s |
| language_detection | · lid.run | 1 | ok | 8.81 s | 2.6 % | +107.67 s |
| language_detection | · lid.run | 1 | ok | 9.60 s | 2.9 % | +116.48 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 186.55 s | 55.5 % | +126.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.34 s | 4.6 % | +126.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.68 s | 4.7 % | +141.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.33 s | 4.6 % | +157.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.29 s | 5.1 % | +172.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.46 s | 4.3 % | +189.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.07 s | 4.5 % | +204.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.50 s | 4.3 % | +219.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.85 s | 4.1 % | +233.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.01 s | 5.4 % | +247.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.63 s | 4.7 % | +265.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.04 s | 5.7 % | +281.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.31 s | 3.7 % | +300.32 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +312.63 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +312.64 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +312.64 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +312.64 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.14 s | 3.9 % | +312.64 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +325.79 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +325.79 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +325.79 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +325.85 s |
| queue | · asr.queue_wait | 1 | ok | 325.85 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +325.86 s |
| queue | · asr.queue_wait | 1 | ok | 325.85 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +325.86 s |
| queue | · asr.queue_wait | 1 | ok | 325.86 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +325.86 s |
| queue | · asr.queue_wait | 1 | ok | 325.86 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +325.87 s |
| queue | · asr.queue_wait | 1 | ok | 325.86 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.81 s | 0.2 % | +326.81 s |
| other | notes.generate | 1 | ok | 8.39 s | — | +327.62 s |
| llm_call | · llm.note_write | 1 | ok | 8.26 s | 2.5 % | +327.71 s |

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
| lid.recording | 90.00 s | 8.84 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 9.72 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 9.39 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 9.01 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 9.70 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 11.06 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 9.02 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 9.09 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 9.53 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 9.21 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 8.32 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 8.81 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 9.60 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 15.34 s | 2.058 |
| asr.chunk | faster_whisper | 9.85 s | 15.68 s | 1.592 |
| asr.chunk | faster_whisper | 7.48 s | 15.33 s | 2.049 |
| asr.chunk | faster_whisper | 10.49 s | 17.28 s | 1.647 |
| asr.chunk | faster_whisper | 7.13 s | 14.46 s | 2.027 |
| asr.chunk | faster_whisper | 7.71 s | 15.07 s | 1.955 |
| asr.chunk | faster_whisper | 7.58 s | 14.50 s | 1.913 |
| asr.chunk | faster_whisper | 6.75 s | 13.85 s | 2.052 |
| asr.chunk | faster_whisper | 12.28 s | 18.01 s | 1.466 |
| asr.chunk | faster_whisper | 9.82 s | 15.63 s | 1.592 |
| asr.chunk | faster_whisper | 14.24 s | 19.03 s | 1.337 |
| asr.chunk | faster_whisper | 2.64 s | 12.31 s | 4.664 |

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
| infer | ok | 13.14 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.81 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.26 s | 2,024 | 0 | 0 | 555 | — (not_supported) |
| **total** |  | 2 |  |  | 9.07 s | 2,036 | 0 | 0 | 561 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,413,080,576 B (2.25 GiB) → 2,412,961,792 B (2.25 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
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

- Top critical-path stages: asr_primary 186.55 s (55.5 %); language_detection 121.30 s (36.1 %); diarization_infer 13.14 s (3.9 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
