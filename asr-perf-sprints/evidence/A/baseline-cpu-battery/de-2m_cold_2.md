# Diagnostics — recording ac9eef4d-99c6-4f5f-a0d2-cac5bbbb27f2

Run `e8653210-e086-41b6-860b-3bc532697c9b` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ac9eef4d-99c6-4f5f-a0d2-cac5bbbb27f2 |
| processing_run_id | e8653210-e086-41b6-860b-3bc532697c9b |
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
| audio duration | 113.87 s |
| processing_wall_seconds | 404.60 s |
| rtf | 3.553 |
| speedup | 0.281 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.32 s | 0.1 % | -0.33 s |
| capture_input | asr.submit.probe | 1 | ok | 0.23 s | 0.1 % | -0.30 s |
| other | worker_job | 1 | ok | 356.27 s | — | +39.85 s |
| queue | · asr.queue_wait | 1 | ok | 39.85 s | 9.8 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.08 s | 0.3 % | +39.91 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +40.99 s |
| model_init | · vad.model | 1 | ok | 3.47 s | 0.9 % | +40.99 s |
| vad | · vad.speech_runs | 1 | ok | 4.22 s | 1.0 % | +44.45 s |
| language_detection | · lid.recording | 1 | ok | 11.17 s | 2.8 % | +48.68 s |
| language_detection | · lid.run | 1 | ok | 10.26 s | 2.5 % | +59.87 s |
| language_detection | · lid.run | 1 | ok | 11.38 s | 2.8 % | +70.14 s |
| language_detection | · lid.run | 1 | ok | 12.14 s | 3.0 % | +81.54 s |
| language_detection | · lid.run | 1 | ok | 14.75 s | 3.6 % | +93.70 s |
| language_detection | · lid.run | 1 | ok | 12.37 s | 3.1 % | +108.46 s |
| language_detection | · lid.run | 1 | ok | 11.79 s | 2.9 % | +120.84 s |
| language_detection | · lid.run | 1 | ok | 10.61 s | 2.6 % | +132.63 s |
| language_detection | · lid.run | 1 | ok | 9.03 s | 2.2 % | +143.25 s |
| language_detection | · lid.run | 1 | ok | 10.91 s | 2.7 % | +152.30 s |
| language_detection | · lid.run | 1 | ok | 11.00 s | 2.7 % | +163.22 s |
| language_detection | · lid.run | 1 | ok | 9.36 s | 2.3 % | +174.22 s |
| language_detection | · lid.run | 1 | ok | 9.07 s | 2.2 % | +183.59 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 185.17 s | 45.8 % | +192.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.95 s | 3.4 % | +192.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.39 s | 3.3 % | +206.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.87 s | 3.7 % | +220.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.09 s | 3.7 % | +234.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.74 s | 3.6 % | +249.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.51 s | 3.6 % | +264.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.78 s | 3.4 % | +279.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.40 s | 3.6 % | +293.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.22 s | 3.8 % | +307.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.60 s | 4.1 % | +322.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.79 s | 3.7 % | +339.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.77 s | 2.9 % | +354.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.98 s | 3.0 % | +365.85 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.06 s | 0.0 % | +377.84 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +377.89 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +377.90 s |
| diarization_load | · diarization.load | 1 | ok | 3.86 s | 1.0 % | +377.90 s |
| diarization_infer | · diarization.infer | 1 | ok | 14.17 s | 3.5 % | +381.76 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +395.94 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +395.95 s |
| persist | · asr.persist | 1 | ok | 0.13 s | 0.0 % | +395.95 s |
| other | worker_job | 1 | skipped | 0.02 s | — | +396.18 s |
| queue | · asr.queue_wait | 1 | ok | 396.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.01 s | — | +396.20 s |
| queue | · asr.queue_wait | 1 | ok | 396.19 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +396.21 s |
| queue | · asr.queue_wait | 1 | ok | 396.20 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +396.22 s |
| queue | · asr.queue_wait | 1 | ok | 396.21 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +396.23 s |
| queue | · asr.queue_wait | 1 | ok | 396.22 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.79 s | 0.2 % | +397.81 s |
| other | notes.generate | 1 | ok | 6.00 s | — | +398.60 s |
| llm_call | · llm.note_write | 1 | ok | 5.79 s | 1.4 % | +398.75 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 97.66 s | 13 | 1.93 s | 8.35 s | 9.95 s |

### Language checks

Language checks: 13.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 11.17 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 10.26 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 11.38 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 12.14 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 14.75 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 12.37 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 11.79 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 10.61 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 9.03 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 10.91 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 11.00 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 9.36 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 9.07 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 13.95 s | 1.581 |
| asr.chunk | faster_whisper | 8.92 s | 13.39 s | 1.500 |
| asr.chunk | faster_whisper | 5.85 s | 14.87 s | 2.541 |
| asr.chunk | faster_whisper | 9.95 s | 15.09 s | 1.517 |
| asr.chunk | faster_whisper | 8.16 s | 14.74 s | 1.807 |
| asr.chunk | faster_whisper | 9.63 s | 14.51 s | 1.507 |
| asr.chunk | faster_whisper | 5.85 s | 13.78 s | 2.354 |
| asr.chunk | faster_whisper | 9.88 s | 14.40 s | 1.457 |
| asr.chunk | faster_whisper | 7.04 s | 15.22 s | 2.163 |
| asr.chunk | faster_whisper | 9.63 s | 16.60 s | 1.724 |
| asr.chunk | faster_whisper | 8.35 s | 14.79 s | 1.772 |
| asr.chunk | faster_whisper | 3.64 s | 11.77 s | 3.231 |
| asr.chunk | faster_whisper | 1.93 s | 11.98 s | 6.203 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 97.66 s |
| audio duration | 113.87 s |
| reprocessing ratio | 0.858 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.86 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 14.17 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.79 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.79 s | 1,820 | 0 | 0 | 350 | — (not_supported) |
| **total** |  | 2 |  |  | 6.58 s | 1,832 | 0 | 0 | 356 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,295,104 B (2.28 GiB) → 2,976,407,552 B (2.77 GiB) |
| swap used | 1,291,780,096 B (1.20 GiB) → 1,296,568,320 B (1.21 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.21 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,175 B |

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

- Top critical-path stages: asr_primary 185.17 s (45.8 %); language_detection 143.86 s (35.6 %); queue 39.85 s (9.8 %).
- Reprocessing ratio: 0.858.
- Cold loads: vad.model 3.47 s; diarization.load 3.86 s.
- Queue wait: 39.85 s.
- LLM latency share of wall: 1.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
