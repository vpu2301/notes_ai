# Diagnostics — recording 38bb7201-4532-4a4b-a691-9e05be9f2a69

Run `41db2816-c4c7-46d1-8a18-b2ce2ad5ab7c` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 38bb7201-4532-4a4b-a691-9e05be9f2a69 |
| processing_run_id | 41db2816-c4c7-46d1-8a18-b2ce2ad5ab7c |
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
| audio duration | 113.84 s |
| processing_wall_seconds | 418.32 s |
| rtf | 3.674 |
| speedup | 0.272 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.10 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 410.33 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.21 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| vad | · vad.speech_runs | 1 | ok | 7.75 s | 1.9 % | +0.24 s |
| language_detection | · lid.recording | 1 | ok | 9.43 s | 2.3 % | +7.99 s |
| language_detection | · lid.run | 1 | ok | 9.64 s | 2.3 % | +17.43 s |
| language_detection | · lid.run | 1 | ok | 9.96 s | 2.4 % | +27.08 s |
| language_detection | · lid.run | 1 | ok | 10.17 s | 2.4 % | +37.04 s |
| language_detection | · lid.run | 1 | ok | 11.23 s | 2.7 % | +47.23 s |
| language_detection | · lid.run | 1 | ok | 12.65 s | 3.0 % | +58.48 s |
| language_detection | · lid.run | 1 | ok | 13.74 s | 3.3 % | +71.32 s |
| language_detection | · lid.run | 1 | ok | 11.66 s | 2.8 % | +85.07 s |
| language_detection | · lid.run | 1 | ok | 11.84 s | 2.8 % | +96.74 s |
| language_detection | · lid.run | 1 | ok | 11.89 s | 2.8 % | +108.60 s |
| language_detection | · lid.run | 1 | ok | 11.64 s | 2.8 % | +120.50 s |
| language_detection | · lid.run | 1 | ok | 9.58 s | 2.3 % | +132.15 s |
| language_detection | · lid.run | 1 | ok | 9.38 s | 2.2 % | +141.73 s |
| language_detection | · lid.run | 1 | ok | 11.08 s | 2.6 % | +151.12 s |
| language_detection | · lid.run | 1 | ok | 9.70 s | 2.3 % | +162.21 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 223.68 s | 53.5 % | +171.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.91 s | 4.3 % | +171.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.08 s | 3.8 % | +189.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.31 s | 3.7 % | +205.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.45 s | 3.9 % | +221.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.14 s | 4.3 % | +237.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.85 s | 4.0 % | +255.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.63 s | 4.5 % | +272.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.80 s | 3.5 % | +291.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.04 s | 3.1 % | +306.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.63 s | 3.5 % | +319.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.15 s | 5.5 % | +333.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.24 s | 3.6 % | +356.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.14 s | 2.9 % | +372.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.21 s | 2.7 % | +384.38 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +395.58 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +395.58 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +395.59 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +395.59 s |
| diarization_infer | · diarization.infer | 1 | ok | 14.67 s | 3.5 % | +395.59 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +410.27 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +410.28 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +410.28 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.35 s |
| queue | · asr.queue_wait | 1 | ok | 410.35 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.36 s |
| queue | · asr.queue_wait | 1 | ok | 410.35 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.36 s |
| queue | · asr.queue_wait | 1 | ok | 410.36 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.37 s |
| queue | · asr.queue_wait | 1 | ok | 410.36 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.38 s |
| queue | · asr.queue_wait | 1 | ok | 410.37 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +410.38 s |
| queue | · asr.queue_wait | 1 | ok | 410.38 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.79 s | 0.2 % | +412.10 s |
| other | notes.generate | 1 | ok | 5.39 s | — | +412.92 s |
| llm_call | · llm.note_write | 1 | ok | 5.22 s | 1.2 % | +413.05 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 100.83 s | 14 | 2.83 s | 6.81 s | 17.12 s |

### Language checks

Language checks: 15.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 9.43 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 9.64 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 9.96 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 10.17 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 11.23 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 12.65 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 13.74 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 11.66 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 11.84 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 11.89 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 11.64 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 9.58 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 9.38 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 11.08 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 9.70 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 17.91 s | 2.787 |
| asr.chunk | faster_whisper | 7.23 s | 16.08 s | 2.225 |
| asr.chunk | faster_whisper | 6.88 s | 15.31 s | 2.226 |
| asr.chunk | faster_whisper | 6.75 s | 16.45 s | 2.438 |
| asr.chunk | faster_whisper | 7.26 s | 18.14 s | 2.498 |
| asr.chunk | faster_whisper | 7.93 s | 16.85 s | 2.125 |
| asr.chunk | faster_whisper | 8.86 s | 18.63 s | 2.103 |
| asr.chunk | faster_whisper | 5.31 s | 14.80 s | 2.788 |
| asr.chunk | faster_whisper | 5.34 s | 13.04 s | 2.442 |
| asr.chunk | faster_whisper | 5.79 s | 14.63 s | 2.527 |
| asr.chunk | faster_whisper | 17.12 s | 23.15 s | 1.353 |
| asr.chunk | faster_whisper | 8.38 s | 15.23 s | 1.818 |
| asr.chunk | faster_whisper | 4.73 s | 12.14 s | 2.566 |
| asr.chunk | faster_whisper | 2.83 s | 11.21 s | 3.953 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 100.83 s |
| audio duration | 113.84 s |
| reprocessing ratio | 0.886 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 14.67 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.79 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.22 s | 1,764 | 0 | 0 | 321 | — (not_supported) |
| **total** |  | 2 |  |  | 6.01 s | 1,776 | 0 | 0 | 327 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,371,395,584 B (2.21 GiB) → 2,408,656,896 B (2.24 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.04 s |
| telemetry buffer peak | 1,603 B |

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

- Top critical-path stages: asr_primary 223.67 s (53.5 %); language_detection 163.63 s (39.1 %); diarization_infer 14.68 s (3.5 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.4 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
