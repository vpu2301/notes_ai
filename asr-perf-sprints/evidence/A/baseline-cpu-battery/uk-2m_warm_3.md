# Diagnostics — recording fa14a4f7-8dce-4816-afa8-c72afc3168a6

Run `5ac8eca0-90ff-4148-976f-6c520287a66e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | fa14a4f7-8dce-4816-afa8-c72afc3168a6 |
| processing_run_id | 5ac8eca0-90ff-4148-976f-6c520287a66e |
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
| processing_wall_seconds | 377.34 s |
| rtf | 3.310 |
| speedup | 0.302 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.21 s | 0.1 % | -0.22 s |
| capture_input | asr.submit.probe | 1 | ok | 0.13 s | 0.0 % | -0.21 s |
| other | worker_job | 1 | ok | 368.10 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.23 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.26 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.26 s |
| vad | · vad.speech_runs | 1 | ok | 4.07 s | 1.1 % | +0.26 s |
| language_detection | · lid.recording | 1 | ok | 9.46 s | 2.5 % | +4.33 s |
| language_detection | · lid.run | 1 | ok | 9.30 s | 2.5 % | +13.82 s |
| language_detection | · lid.run | 1 | ok | 9.45 s | 2.5 % | +23.12 s |
| language_detection | · lid.run | 1 | ok | 8.85 s | 2.3 % | +32.57 s |
| language_detection | · lid.run | 1 | ok | 10.58 s | 2.8 % | +41.42 s |
| language_detection | · lid.run | 1 | ok | 9.01 s | 2.4 % | +52.01 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 2.4 % | +61.02 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | 2.4 % | +70.16 s |
| language_detection | · lid.run | 1 | ok | 10.15 s | 2.7 % | +79.17 s |
| language_detection | · lid.run | 1 | ok | 8.92 s | 2.4 % | +89.33 s |
| language_detection | · lid.run | 1 | ok | 9.10 s | 2.4 % | +98.26 s |
| language_detection | · lid.run | 1 | ok | 9.85 s | 2.6 % | +107.36 s |
| language_detection | · lid.run | 1 | ok | 10.88 s | 2.9 % | +117.23 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 222.46 s | 59.0 % | +128.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.70 s | 4.7 % | +128.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.14 s | 5.1 % | +145.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.36 s | 4.1 % | +164.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.13 s | 5.1 % | +180.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.99 s | 4.8 % | +199.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.63 s | 4.9 % | +217.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.07 s | 4.5 % | +236.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.41 s | 4.1 % | +253.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.61 s | 6.3 % | +268.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.29 s | 5.4 % | +292.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 24.41 s | 6.5 % | +312.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.62 s | 3.6 % | +336.94 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +350.57 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +350.57 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +350.58 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +350.58 s |
| diarization_infer | · diarization.infer | 1 | ok | 17.49 s | 4.6 % | +350.58 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +368.07 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +368.07 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +368.08 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +368.14 s |
| queue | · asr.queue_wait | 1 | ok | 368.13 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +368.14 s |
| queue | · asr.queue_wait | 1 | ok | 368.13 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +368.14 s |
| queue | · asr.queue_wait | 1 | ok | 368.14 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +368.15 s |
| queue | · asr.queue_wait | 1 | ok | 368.14 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +368.15 s |
| queue | · asr.queue_wait | 1 | ok | 368.14 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.59 s | 0.2 % | +368.61 s |
| other | notes.generate | 1 | ok | 8.14 s | — | +369.20 s |
| llm_call | · llm.note_write | 1 | ok | 8.02 s | 2.1 % | +369.27 s |

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
| lid.recording | 90.00 s | 9.46 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 9.30 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 9.45 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 8.85 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 10.58 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 9.01 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 9.14 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 9.00 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 10.15 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 8.92 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 9.10 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 9.85 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 10.88 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 17.70 s | 2.376 |
| asr.chunk | faster_whisper | 9.85 s | 19.14 s | 1.942 |
| asr.chunk | faster_whisper | 7.48 s | 15.36 s | 2.052 |
| asr.chunk | faster_whisper | 10.49 s | 19.13 s | 1.823 |
| asr.chunk | faster_whisper | 7.13 s | 17.99 s | 2.522 |
| asr.chunk | faster_whisper | 7.71 s | 18.63 s | 2.417 |
| asr.chunk | faster_whisper | 7.58 s | 17.06 s | 2.251 |
| asr.chunk | faster_whisper | 6.75 s | 15.41 s | 2.284 |
| asr.chunk | faster_whisper | 12.28 s | 23.61 s | 1.922 |
| asr.chunk | faster_whisper | 9.82 s | 20.29 s | 2.067 |
| asr.chunk | faster_whisper | 14.24 s | 24.41 s | 1.715 |
| asr.chunk | faster_whisper | 2.64 s | 13.62 s | 5.162 |

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
| infer | ok | 17.49 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.59 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.02 s | 2,024 | 0 | 0 | 523 | — (not_supported) |
| **total** |  | 2 |  |  | 8.61 s | 2,036 | 0 | 0 | 529 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,413,338,624 B (2.25 GiB) → 2,413,150,208 B (2.25 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,593 B |

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

- Top critical-path stages: asr_primary 222.46 s (59.0 %); language_detection 123.70 s (32.8 %); diarization_infer 17.49 s (4.6 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
