# Diagnostics — recording 99510239-d258-4a0e-8607-5937d19a0a58

Run `053f9549-8d2b-4128-af9d-3ccb9dcd1158` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 99510239-d258-4a0e-8607-5937d19a0a58 |
| processing_run_id | 053f9549-8d2b-4128-af9d-3ccb9dcd1158 |
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
| processing_wall_seconds | 371.94 s |
| rtf | 3.263 |
| speedup | 0.307 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.73 s | 0.2 % | -0.75 s |
| capture_input | asr.submit.probe | 1 | ok | 0.52 s | 0.1 % | -0.67 s |
| other | worker_job | 1 | ok | 331.14 s | — | +28.66 s |
| queue | · asr.queue_wait | 1 | ok | 28.65 s | 7.7 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.95 s | 0.3 % | +28.67 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +29.63 s |
| model_init | · vad.model | 1 | ok | 2.93 s | 0.8 % | +29.63 s |
| vad | · vad.speech_runs | 1 | ok | 3.67 s | 1.0 % | +32.56 s |
| language_detection | · lid.recording | 1 | ok | 9.67 s | 2.6 % | +36.24 s |
| language_detection | · lid.run | 1 | ok | 8.50 s | 2.3 % | +45.91 s |
| language_detection | · lid.run | 1 | ok | 8.34 s | 2.2 % | +54.42 s |
| language_detection | · lid.run | 1 | ok | 8.67 s | 2.3 % | +62.77 s |
| language_detection | · lid.run | 1 | ok | 8.06 s | 2.2 % | +71.44 s |
| language_detection | · lid.run | 1 | ok | 8.43 s | 2.3 % | +79.51 s |
| language_detection | · lid.run | 1 | ok | 10.66 s | 2.9 % | +87.94 s |
| language_detection | · lid.run | 1 | ok | 9.49 s | 2.6 % | +98.63 s |
| language_detection | · lid.run | 1 | ok | 9.47 s | 2.5 % | +108.12 s |
| language_detection | · lid.run | 1 | ok | 11.69 s | 3.1 % | +117.61 s |
| language_detection | · lid.run | 1 | ok | 8.53 s | 2.3 % | +129.29 s |
| language_detection | · lid.run | 1 | ok | 8.55 s | 2.3 % | +137.82 s |
| language_detection | · lid.run | 1 | ok | 8.53 s | 2.3 % | +146.38 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 187.64 s | 50.5 % | +154.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.79 s | 4.0 % | +154.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.84 s | 4.5 % | +169.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.24 s | 3.8 % | +186.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.79 s | 4.2 % | +200.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.99 s | 3.8 % | +216.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.38 s | 4.9 % | +230.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.96 s | 4.0 % | +248.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.50 s | 3.9 % | +263.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.33 s | 4.4 % | +278.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.35 s | 4.1 % | +294.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.71 s | 5.0 % | +310.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.68 s | 3.7 % | +328.83 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +342.52 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +342.55 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +342.55 s |
| diarization_load | · diarization.load | 1 | ok | 3.74 s | 1.0 % | +342.55 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.35 s | 3.6 % | +346.29 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +359.64 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +359.65 s |
| persist | · asr.persist | 1 | ok | 0.09 s | 0.0 % | +359.65 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +359.78 s |
| queue | · asr.queue_wait | 1 | ok | 359.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +359.79 s |
| queue | · asr.queue_wait | 1 | ok | 359.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +359.79 s |
| queue | · asr.queue_wait | 1 | ok | 359.78 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.72 s | 0.2 % | +361.78 s |
| other | notes.generate | 1 | ok | 9.44 s | — | +362.50 s |
| llm_call | · llm.note_write | 1 | ok | 9.23 s | 2.5 % | +362.58 s |

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
| lid.recording | 90.00 s | 9.67 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 8.50 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 8.34 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 8.67 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 8.06 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 8.43 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 10.66 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 9.49 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 9.47 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 11.69 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 8.53 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 8.55 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 8.53 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 14.79 s | 1.985 |
| asr.chunk | faster_whisper | 9.85 s | 16.84 s | 1.710 |
| asr.chunk | faster_whisper | 7.48 s | 14.24 s | 1.902 |
| asr.chunk | faster_whisper | 10.49 s | 15.79 s | 1.505 |
| asr.chunk | faster_whisper | 7.13 s | 13.99 s | 1.962 |
| asr.chunk | faster_whisper | 7.71 s | 18.37 s | 2.384 |
| asr.chunk | faster_whisper | 7.58 s | 14.96 s | 1.973 |
| asr.chunk | faster_whisper | 6.75 s | 14.50 s | 2.148 |
| asr.chunk | faster_whisper | 12.28 s | 16.33 s | 1.330 |
| asr.chunk | faster_whisper | 9.82 s | 15.35 s | 1.563 |
| asr.chunk | faster_whisper | 14.24 s | 18.71 s | 1.314 |
| asr.chunk | faster_whisper | 2.64 s | 13.68 s | 5.184 |

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
| load | ok | 3.74 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 13.34 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.71 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 9.22 s | 2,024 | 0 | 0 | 502 | — (not_supported) |
| **total** |  | 2 |  |  | 9.94 s | 2,036 | 0 | 0 | 508 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,485,888 B (2.29 GiB) → 3,037,724,672 B (2.83 GiB) |
| swap used | 1,418,706,944 B (1.32 GiB) → 1,419,554,816 B (1.32 GiB) |
| memory pressure | some_avg10=0.10 → some_avg10=0.54 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.03 s |
| telemetry buffer peak | 1,172 B |

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

- Top critical-path stages: asr_primary 187.61 s (50.4 %); language_detection 118.58 s (31.9 %); queue 28.65 s (7.7 %).
- Reprocessing ratio: 0.907.
- Cold loads: vad.model 2.93 s; diarization.load 3.74 s.
- Queue wait: 28.65 s.
- LLM latency share of wall: 2.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
