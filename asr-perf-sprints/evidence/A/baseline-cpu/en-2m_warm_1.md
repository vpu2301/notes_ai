# Diagnostics — recording 01834f28-cd7d-446e-a107-43dc59d7f1f5

Run `1ca2da08-1924-4f4a-b851-109c5d1b8ce8` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 01834f28-cd7d-446e-a107-43dc59d7f1f5 |
| processing_run_id | 1ca2da08-1924-4f4a-b851-109c5d1b8ce8 |
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
| processing_wall_seconds | 241.98 s |
| rtf | 2.125 |
| speedup | 0.470 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.16 s | 0.1 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 236.91 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.13 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.16 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.16 s |
| vad | · vad.speech_runs | 1 | ok | 5.18 s | 2.1 % | +0.16 s |
| language_detection | · lid.recording | 1 | ok | 6.92 s | 2.9 % | +5.34 s |
| language_detection | · lid.run | 1 | ok | 7.10 s | 2.9 % | +12.26 s |
| language_detection | · lid.run | 1 | ok | 8.16 s | 3.4 % | +19.36 s |
| language_detection | · lid.run | 1 | ok | 7.87 s | 3.3 % | +27.53 s |
| language_detection | · lid.run | 1 | ok | 7.40 s | 3.1 % | +35.41 s |
| language_detection | · lid.run | 1 | ok | 6.83 s | 2.8 % | +42.82 s |
| language_detection | · lid.run | 1 | ok | 5.98 s | 2.5 % | +49.65 s |
| language_detection | · lid.run | 1 | ok | 6.29 s | 2.6 % | +55.63 s |
| language_detection | · lid.run | 1 | ok | 6.41 s | 2.6 % | +61.92 s |
| language_detection | · lid.run | 1 | ok | 6.36 s | 2.6 % | +68.33 s |
| language_detection | · lid.run | 1 | ok | 6.26 s | 2.6 % | +74.70 s |
| language_detection | · lid.run | 1 | ok | 6.55 s | 2.7 % | +80.97 s |
| language_detection | · lid.run | 1 | ok | 6.61 s | 2.7 % | +87.52 s |
| language_detection | · lid.run | 1 | ok | 6.35 s | 2.6 % | +94.13 s |
| language_detection | · lid.run | 1 | ok | 5.96 s | 2.5 % | +100.48 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 123.69 s | 51.1 % | +106.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 4.1 % | +106.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.71 s | 3.6 % | +116.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.36 s | 3.5 % | +125.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.59 s | 3.6 % | +133.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.90 s | 3.7 % | +142.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.22 s | 3.8 % | +150.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.99 s | 4.1 % | +160.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.92 s | 3.3 % | +170.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.06 s | 3.3 % | +178.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 3.3 % | +186.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.30 s | 5.1 % | +194.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.19 s | 3.8 % | +206.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.57 s | 3.1 % | +215.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.96 s | 2.9 % | +223.16 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +230.13 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +230.13 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +230.14 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +230.14 s |
| diarization_infer | · diarization.infer | 1 | ok | 6.70 s | 2.8 % | +230.14 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +236.84 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +236.85 s |
| persist | · asr.persist | 1 | ok | 0.06 s | 0.0 % | +236.85 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +236.93 s |
| queue | · asr.queue_wait | 1 | ok | 236.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +236.93 s |
| queue | · asr.queue_wait | 1 | ok | 236.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +236.93 s |
| queue | · asr.queue_wait | 1 | ok | 236.93 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.81 s | 0.3 % | +237.65 s |
| other | notes.generate | 1 | ok | 3.52 s | — | +238.46 s |
| llm_call | · llm.note_write | 1 | ok | 3.41 s | 1.4 % | +238.52 s |

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
| lid.recording | 90.00 s | 6.92 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 7.10 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 8.16 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 7.87 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 7.40 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 6.83 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 5.98 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 6.29 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 6.41 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 6.36 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 6.26 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 6.55 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 6.61 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 6.35 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 5.96 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 9.89 s | 1.539 |
| asr.chunk | faster_whisper | 7.23 s | 8.71 s | 1.205 |
| asr.chunk | faster_whisper | 6.88 s | 8.36 s | 1.216 |
| asr.chunk | faster_whisper | 6.75 s | 8.59 s | 1.274 |
| asr.chunk | faster_whisper | 7.26 s | 8.90 s | 1.226 |
| asr.chunk | faster_whisper | 7.93 s | 9.22 s | 1.163 |
| asr.chunk | faster_whisper | 8.86 s | 9.99 s | 1.127 |
| asr.chunk | faster_whisper | 5.31 s | 7.92 s | 1.491 |
| asr.chunk | faster_whisper | 5.34 s | 8.06 s | 1.508 |
| asr.chunk | faster_whisper | 5.79 s | 7.98 s | 1.378 |
| asr.chunk | faster_whisper | 17.12 s | 12.29 s | 0.718 |
| asr.chunk | faster_whisper | 8.38 s | 9.19 s | 1.097 |
| asr.chunk | faster_whisper | 4.73 s | 7.57 s | 1.601 |
| asr.chunk | faster_whisper | 2.83 s | 6.96 s | 2.456 |

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
| infer | ok | 6.70 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.81 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 3.41 s | 1,764 | 0 | 0 | 264 | — (not_supported) |
| **total** |  | 2 |  |  | 4.22 s | 1,776 | 0 | 0 | 270 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,093,688,320 B (2.88 GiB) → 2,394,402,816 B (2.23 GiB) |
| swap used | 31,252,480 B (0.03 GiB) → 50,827,264 B (0.05 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,602 B |

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

- Top critical-path stages: asr_primary 123.69 s (51.1 %); language_detection 101.04 s (41.8 %); diarization_infer 6.70 s (2.8 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
