# Diagnostics — recording 84ddc328-b2a0-4b7e-ad89-d11bf4c64f97

Run `0ea888db-2569-4b7c-bfbf-ae819fc290e8` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 84ddc328-b2a0-4b7e-ad89-d11bf4c64f97 |
| processing_run_id | 0ea888db-2569-4b7c-bfbf-ae819fc290e8 |
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
| processing_wall_seconds | 192.86 s |
| rtf | 1.692 |
| speedup | 0.591 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.11 s | 0.1 % | -0.11 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.10 s |
| other | worker_job | 1 | ok | 181.48 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.14 s | 0.1 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.16 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.16 s |
| vad | · vad.speech_runs | 1 | ok | 2.82 s | 1.5 % | +0.16 s |
| language_detection | · lid.recording | 1 | ok | 5.88 s | 3.0 % | +2.98 s |
| language_detection | · lid.run | 1 | ok | 4.97 s | 2.6 % | +8.86 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 2.6 % | +13.84 s |
| language_detection | · lid.run | 1 | ok | 4.97 s | 2.6 % | +18.87 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.6 % | +23.84 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 2.9 % | +28.76 s |
| language_detection | · lid.run | 1 | ok | 5.22 s | 2.7 % | +34.33 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 2.5 % | +39.55 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.6 % | +44.47 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 2.6 % | +49.56 s |
| language_detection | · lid.run | 1 | ok | 5.01 s | 2.6 % | +54.62 s |
| language_detection | · lid.run | 1 | ok | 5.07 s | 2.6 % | +59.64 s |
| language_detection | · lid.run | 1 | ok | 5.05 s | 2.6 % | +64.72 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 103.98 s | 53.9 % | +69.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 4.2 % | +69.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.11 s | 4.7 % | +77.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.42 s | 4.4 % | +86.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.97 s | 4.7 % | +95.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 4.2 % | +104.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.82 s | 4.6 % | +112.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.56 s | 4.4 % | +121.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.73 s | 4.0 % | +129.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.83 s | 5.1 % | +137.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.35 s | 4.8 % | +147.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.55 s | 5.5 % | +156.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.43 s | 3.3 % | +167.32 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +173.75 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +173.75 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +173.76 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +173.76 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.70 s | 4.0 % | +173.76 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +181.46 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +181.46 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +181.46 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +181.50 s |
| queue | · asr.queue_wait | 1 | ok | 181.50 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +181.51 s |
| queue | · asr.queue_wait | 1 | ok | 181.50 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 1.47 s | 0.8 % | +182.95 s |
| other | notes.generate | 1 | ok | 8.44 s | — | +184.42 s |
| llm_call | · llm.note_write | 1 | ok | 8.37 s | 4.3 % | +184.44 s |

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
| lid.recording | 90.00 s | 5.88 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 4.97 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 5.03 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 4.97 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 4.92 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 5.56 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 5.22 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 4.92 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 5.09 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 5.06 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 5.01 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 5.07 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 5.05 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 8.08 s | 1.085 |
| asr.chunk | faster_whisper | 9.85 s | 9.11 s | 0.925 |
| asr.chunk | faster_whisper | 7.48 s | 8.42 s | 1.125 |
| asr.chunk | faster_whisper | 10.49 s | 8.97 s | 0.855 |
| asr.chunk | faster_whisper | 7.13 s | 8.08 s | 1.133 |
| asr.chunk | faster_whisper | 7.71 s | 8.82 s | 1.145 |
| asr.chunk | faster_whisper | 7.58 s | 8.56 s | 1.130 |
| asr.chunk | faster_whisper | 6.75 s | 7.73 s | 1.145 |
| asr.chunk | faster_whisper | 12.28 s | 9.83 s | 0.800 |
| asr.chunk | faster_whisper | 9.82 s | 9.35 s | 0.952 |
| asr.chunk | faster_whisper | 14.24 s | 10.55 s | 0.741 |
| asr.chunk | faster_whisper | 2.64 s | 6.43 s | 2.438 |

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
| infer | ok | 7.70 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.47 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.37 s | 2,024 | 0 | 0 | 522 | — (not_supported) |
| **total** |  | 2 |  |  | 9.84 s | 2,036 | 0 | 0 | 528 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,101,040,640 B (2.89 GiB) → 3,106,672,640 B (2.89 GiB) |
| swap used | 110,972,928 B (0.10 GiB) → 111,308,800 B (0.10 GiB) |
| memory pressure | some_avg10=0.04 → some_avg10=0.18 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.03 s |
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

- Top critical-path stages: asr_primary 103.99 s (53.9 %); language_detection 66.76 s (34.6 %); llm_call 9.84 s (5.1 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 5.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
