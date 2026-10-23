# Diagnostics — recording 4bc7715a-ba90-48f5-8cb7-eb8ba50bd6c2

Run `44c2dadc-a787-4bd6-89a9-6079fee0e805` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 4bc7715a-ba90-48f5-8cb7-eb8ba50bd6c2 |
| processing_run_id | 44c2dadc-a787-4bd6-89a9-6079fee0e805 |
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
| processing_wall_seconds | 355.70 s |
| rtf | 3.120 |
| speedup | 0.320 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.10 s | 0.0 % | -0.14 s |
| other | worker_job | 1 | ok | 344.63 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.23 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.25 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.25 s |
| vad | · vad.speech_runs | 1 | ok | 4.07 s | 1.1 % | +0.25 s |
| language_detection | · lid.recording | 1 | ok | 8.88 s | 2.5 % | +4.32 s |
| language_detection | · lid.run | 1 | ok | 9.34 s | 2.6 % | +13.21 s |
| language_detection | · lid.run | 1 | ok | 9.86 s | 2.8 % | +22.56 s |
| language_detection | · lid.run | 1 | ok | 9.01 s | 2.5 % | +32.41 s |
| language_detection | · lid.run | 1 | ok | 8.73 s | 2.5 % | +41.42 s |
| language_detection | · lid.run | 1 | ok | 8.68 s | 2.4 % | +50.16 s |
| language_detection | · lid.run | 1 | ok | 9.17 s | 2.6 % | +58.85 s |
| language_detection | · lid.run | 1 | ok | 8.57 s | 2.4 % | +68.02 s |
| language_detection | · lid.run | 1 | ok | 8.64 s | 2.4 % | +76.60 s |
| language_detection | · lid.run | 1 | ok | 9.89 s | 2.8 % | +85.24 s |
| language_detection | · lid.run | 1 | ok | 9.64 s | 2.7 % | +95.13 s |
| language_detection | · lid.run | 1 | ok | 9.37 s | 2.6 % | +104.77 s |
| language_detection | · lid.run | 1 | ok | 9.65 s | 2.7 % | +114.15 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 208.27 s | 58.6 % | +123.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.09 s | 5.1 % | +123.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.28 s | 6.0 % | +141.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.15 s | 5.4 % | +163.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.93 s | 5.0 % | +182.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.58 s | 4.9 % | +200.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.12 s | 5.4 % | +217.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.05 s | 4.8 % | +237.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.88 s | 3.9 % | +254.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.84 s | 5.0 % | +267.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.52 s | 4.4 % | +285.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.55 s | 5.5 % | +301.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.20 s | 3.1 % | +320.87 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +332.07 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +332.07 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +332.07 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +332.07 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.48 s | 3.5 % | +332.07 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +344.56 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +344.56 s |
| persist | · asr.persist | 1 | ok | 0.06 s | 0.0 % | +344.57 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.65 s |
| queue | · asr.queue_wait | 1 | ok | 344.65 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.66 s |
| queue | · asr.queue_wait | 1 | ok | 344.66 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.67 s |
| queue | · asr.queue_wait | 1 | ok | 344.66 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +344.67 s |
| queue | · asr.queue_wait | 1 | ok | 344.67 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.97 s | 0.3 % | +346.33 s |
| other | notes.generate | 1 | ok | 8.40 s | — | +347.30 s |
| llm_call | · llm.note_write | 1 | ok | 8.31 s | 2.3 % | +347.35 s |

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
| lid.recording | 90.00 s | 8.88 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 9.34 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 9.86 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 9.01 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 8.73 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 8.68 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 9.17 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 8.57 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 8.64 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 9.89 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 9.64 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 9.37 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 9.65 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 18.09 s | 2.428 |
| asr.chunk | faster_whisper | 9.85 s | 21.28 s | 2.160 |
| asr.chunk | faster_whisper | 7.48 s | 19.15 s | 2.559 |
| asr.chunk | faster_whisper | 10.49 s | 17.93 s | 1.708 |
| asr.chunk | faster_whisper | 7.13 s | 17.57 s | 2.464 |
| asr.chunk | faster_whisper | 7.71 s | 19.12 s | 2.481 |
| asr.chunk | faster_whisper | 7.58 s | 17.05 s | 2.250 |
| asr.chunk | faster_whisper | 6.75 s | 13.88 s | 2.057 |
| asr.chunk | faster_whisper | 12.28 s | 17.84 s | 1.452 |
| asr.chunk | faster_whisper | 9.82 s | 15.52 s | 1.581 |
| asr.chunk | faster_whisper | 14.24 s | 19.55 s | 1.373 |
| asr.chunk | faster_whisper | 2.64 s | 11.20 s | 4.243 |

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
| infer | ok | 12.48 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.97 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.31 s | 2,024 | 0 | 0 | 533 | — (not_supported) |
| **total** |  | 2 |  |  | 9.28 s | 2,036 | 0 | 0 | 539 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,409,177,088 B (2.24 GiB) → 2,412,560,384 B (2.25 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,592 B |

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

- Top critical-path stages: asr_primary 208.26 s (58.6 %); language_detection 119.43 s (33.6 %); diarization_infer 12.48 s (3.5 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
