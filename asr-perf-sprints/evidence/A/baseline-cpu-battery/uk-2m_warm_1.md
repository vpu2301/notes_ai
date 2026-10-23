# Diagnostics — recording df1a075e-20d9-4ac2-9d87-0f174f04c7df

Run `5a0c4fcd-4725-4b63-bf04-7c8de0735718` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | df1a075e-20d9-4ac2-9d87-0f174f04c7df |
| processing_run_id | 5a0c4fcd-4725-4b63-bf04-7c8de0735718 |
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
| processing_wall_seconds | 334.12 s |
| rtf | 2.931 |
| speedup | 0.341 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.09 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 322.49 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.18 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.20 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.20 s |
| vad | · vad.speech_runs | 1 | ok | 2.84 s | 0.8 % | +0.20 s |
| language_detection | · lid.recording | 1 | ok | 8.24 s | 2.5 % | +3.04 s |
| language_detection | · lid.run | 1 | ok | 8.75 s | 2.6 % | +11.28 s |
| language_detection | · lid.run | 1 | ok | 8.71 s | 2.6 % | +20.04 s |
| language_detection | · lid.run | 1 | ok | 8.82 s | 2.6 % | +28.76 s |
| language_detection | · lid.run | 1 | ok | 8.85 s | 2.6 % | +37.58 s |
| language_detection | · lid.run | 1 | ok | 9.55 s | 2.9 % | +46.43 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 2.7 % | +55.98 s |
| language_detection | · lid.run | 1 | ok | 8.78 s | 2.6 % | +64.92 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 2.7 % | +73.70 s |
| language_detection | · lid.run | 1 | ok | 8.35 s | 2.5 % | +82.72 s |
| language_detection | · lid.run | 1 | ok | 8.64 s | 2.6 % | +91.10 s |
| language_detection | · lid.run | 1 | ok | 9.07 s | 2.7 % | +99.74 s |
| language_detection | · lid.run | 1 | ok | 9.04 s | 2.7 % | +108.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 191.79 s | 57.4 % | +117.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.50 s | 4.6 % | +117.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.81 s | 5.0 % | +133.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.12 s | 4.5 % | +150.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.13 s | 5.1 % | +165.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.35 s | 4.3 % | +182.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.77 s | 5.6 % | +196.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.61 s | 4.7 % | +215.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.59 s | 4.4 % | +231.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.62 s | 5.3 % | +245.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.34 s | 4.9 % | +263.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.92 s | 5.7 % | +279.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.97 s | 3.3 % | +298.67 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +309.64 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +309.64 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +309.65 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +309.65 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.82 s | 3.8 % | +309.65 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +322.47 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +322.48 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +322.48 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +322.54 s |
| queue | · asr.queue_wait | 1 | ok | 322.54 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +322.55 s |
| queue | · asr.queue_wait | 1 | ok | 322.54 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +322.55 s |
| queue | · asr.queue_wait | 1 | ok | 322.55 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +322.56 s |
| queue | · asr.queue_wait | 1 | ok | 322.55 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.68 s | 0.2 % | +324.19 s |
| other | notes.generate | 1 | ok | 9.25 s | — | +324.87 s |
| llm_call | · llm.note_write | 1 | ok | 9.14 s | 2.7 % | +324.92 s |

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
| lid.recording | 90.00 s | 8.24 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 8.75 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 8.71 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 8.82 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 8.85 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 9.55 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 8.93 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 8.78 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 9.02 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 8.35 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 8.64 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 9.07 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 9.04 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 15.50 s | 2.080 |
| asr.chunk | faster_whisper | 9.85 s | 16.81 s | 1.707 |
| asr.chunk | faster_whisper | 7.48 s | 15.12 s | 2.020 |
| asr.chunk | faster_whisper | 10.49 s | 17.13 s | 1.633 |
| asr.chunk | faster_whisper | 7.13 s | 14.35 s | 2.012 |
| asr.chunk | faster_whisper | 7.71 s | 18.77 s | 2.435 |
| asr.chunk | faster_whisper | 7.58 s | 15.61 s | 2.060 |
| asr.chunk | faster_whisper | 6.75 s | 14.59 s | 2.162 |
| asr.chunk | faster_whisper | 12.28 s | 17.62 s | 1.434 |
| asr.chunk | faster_whisper | 9.82 s | 16.33 s | 1.663 |
| asr.chunk | faster_whisper | 14.24 s | 18.92 s | 1.329 |
| asr.chunk | faster_whisper | 2.64 s | 10.97 s | 4.155 |

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
| infer | ok | 12.82 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.68 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 9.14 s | 2,024 | 0 | 0 | 573 | — (not_supported) |
| **total** |  | 2 |  |  | 9.81 s | 2,036 | 0 | 0 | 579 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,412,888,064 B (2.25 GiB) → 2,412,695,552 B (2.25 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,591 B |

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

- Top critical-path stages: asr_primary 191.79 s (57.4 %); language_detection 114.77 s (34.4 %); diarization_infer 12.82 s (3.8 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
