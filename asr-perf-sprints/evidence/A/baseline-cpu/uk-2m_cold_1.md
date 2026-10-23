# Diagnostics — recording 02b0b1df-4279-40fa-88a8-5efa502a2627

Run `08640c47-e1fe-43c0-81c2-1794b3959bd2` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 02b0b1df-4279-40fa-88a8-5efa502a2627 |
| processing_run_id | 08640c47-e1fe-43c0-81c2-1794b3959bd2 |
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
| processing_wall_seconds | 236.10 s |
| rtf | 2.071 |
| speedup | 0.483 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.14 s | 0.1 % | -0.14 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 210.29 s | — | +10.35 s |
| queue | · asr.queue_wait | 1 | ok | 10.35 s | 4.4 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.34 s | 0.1 % | +10.37 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +10.71 s |
| model_init | · vad.model | 1 | ok | 1.34 s | 0.6 % | +10.71 s |
| vad | · vad.speech_runs | 1 | ok | 2.16 s | 0.9 % | +12.05 s |
| language_detection | · lid.recording | 1 | ok | 5.61 s | 2.4 % | +14.21 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.1 % | +19.83 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.1 % | +24.75 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 2.1 % | +29.61 s |
| language_detection | · lid.run | 1 | ok | 5.16 s | 2.2 % | +34.50 s |
| language_detection | · lid.run | 1 | ok | 4.87 s | 2.1 % | +39.66 s |
| language_detection | · lid.run | 1 | ok | 4.95 s | 2.1 % | +44.52 s |
| language_detection | · lid.run | 1 | ok | 4.79 s | 2.0 % | +49.48 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.1 % | +54.27 s |
| language_detection | · lid.run | 1 | ok | 5.75 s | 2.4 % | +59.19 s |
| language_detection | · lid.run | 1 | ok | 6.06 s | 2.6 % | +64.94 s |
| language_detection | · lid.run | 1 | ok | 4.96 s | 2.1 % | +71.01 s |
| language_detection | · lid.run | 1 | ok | 5.85 s | 2.5 % | +75.97 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 129.95 s | 55.0 % | +81.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.85 s | 4.2 % | +81.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.01 s | 5.5 % | +91.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.83 s | 4.6 % | +104.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.36 s | 5.2 % | +115.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.14 s | 4.7 % | +127.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.38 s | 4.4 % | +139.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.03 s | 4.2 % | +149.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.08 s | 3.8 % | +159.48 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.24 s | 5.2 % | +168.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.64 s | 4.5 % | +180.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.54 s | 5.3 % | +191.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.78 s | 3.3 % | +204.00 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +211.78 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +211.80 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +211.80 s |
| diarization_load | · diarization.load | 1 | ok | 1.72 s | 0.7 % | +211.80 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.10 s | 3.0 % | +213.52 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +220.62 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +220.62 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +220.62 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +220.65 s |
| queue | · asr.queue_wait | 1 | ok | 220.65 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +220.65 s |
| queue | · asr.queue_wait | 1 | ok | 220.65 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +220.66 s |
| queue | · asr.queue_wait | 1 | ok | 220.65 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 1.82 s | 0.8 % | +222.19 s |
| other | notes.generate | 1 | ok | 12.09 s | — | +224.01 s |
| llm_call | · llm.note_write | 1 | ok | 11.99 s | 5.1 % | +224.06 s |

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
| lid.recording | 90.00 s | 5.61 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 4.92 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 4.85 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 4.89 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 5.16 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 4.87 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 4.95 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 4.79 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 4.92 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 5.75 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 6.06 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 4.96 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 5.85 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 9.85 s | 1.322 |
| asr.chunk | faster_whisper | 9.85 s | 13.01 s | 1.320 |
| asr.chunk | faster_whisper | 7.48 s | 10.83 s | 1.447 |
| asr.chunk | faster_whisper | 10.49 s | 12.36 s | 1.178 |
| asr.chunk | faster_whisper | 7.13 s | 11.14 s | 1.562 |
| asr.chunk | faster_whisper | 7.71 s | 10.38 s | 1.347 |
| asr.chunk | faster_whisper | 7.58 s | 10.03 s | 1.323 |
| asr.chunk | faster_whisper | 6.75 s | 9.08 s | 1.346 |
| asr.chunk | faster_whisper | 12.28 s | 12.24 s | 0.996 |
| asr.chunk | faster_whisper | 9.82 s | 10.64 s | 1.083 |
| asr.chunk | faster_whisper | 14.24 s | 12.54 s | 0.881 |
| asr.chunk | faster_whisper | 2.64 s | 7.78 s | 2.946 |

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
| load | ok | 1.72 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 7.10 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.82 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 11.99 s | 2,024 | 0 | 0 | 573 | — (not_supported) |
| **total** |  | 2 |  |  | 13.80 s | 2,036 | 0 | 0 | 579 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,965,120 B (2.29 GiB) → 3,110,621,184 B (2.90 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.16 → some_avg10=0.12 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,171 B |

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

- Top critical-path stages: asr_primary 129.95 s (55.0 %); language_detection 67.57 s (28.6 %); llm_call 13.80 s (5.8 %).
- Reprocessing ratio: 0.907.
- Cold loads: vad.model 1.34 s; diarization.load 1.72 s.
- Queue wait: 10.35 s.
- LLM latency share of wall: 5.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
