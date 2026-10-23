# Diagnostics — recording 27aa87fe-de39-436d-aa69-7bc00ff9fe22

Run `649e8195-8bc1-478c-b4ff-cd35e1f2e0f0` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 27aa87fe-de39-436d-aa69-7bc00ff9fe22 |
| processing_run_id | 649e8195-8bc1-478c-b4ff-cd35e1f2e0f0 |
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
| processing_wall_seconds | 348.15 s |
| rtf | 3.057 |
| speedup | 0.327 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.23 s | 0.1 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.12 s | 0.0 % | -0.19 s |
| other | worker_job | 1 | ok | 338.01 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.20 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.23 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.23 s |
| vad | · vad.speech_runs | 1 | ok | 4.69 s | 1.3 % | +0.23 s |
| language_detection | · lid.recording | 1 | ok | 9.44 s | 2.7 % | +4.92 s |
| language_detection | · lid.run | 1 | ok | 8.91 s | 2.6 % | +14.37 s |
| language_detection | · lid.run | 1 | ok | 8.29 s | 2.4 % | +23.28 s |
| language_detection | · lid.run | 1 | ok | 9.13 s | 2.6 % | +31.57 s |
| language_detection | · lid.run | 1 | ok | 9.94 s | 2.9 % | +40.71 s |
| language_detection | · lid.run | 1 | ok | 8.47 s | 2.4 % | +50.66 s |
| language_detection | · lid.run | 1 | ok | 8.34 s | 2.4 % | +59.13 s |
| language_detection | · lid.run | 1 | ok | 14.76 s | 4.2 % | +67.47 s |
| language_detection | · lid.run | 1 | ok | 8.57 s | 2.5 % | +82.24 s |
| language_detection | · lid.run | 1 | ok | 9.27 s | 2.7 % | +90.82 s |
| language_detection | · lid.run | 1 | ok | 8.40 s | 2.4 % | +100.10 s |
| language_detection | · lid.run | 1 | ok | 9.09 s | 2.6 % | +108.50 s |
| language_detection | · lid.run | 1 | ok | 10.11 s | 2.9 % | +117.60 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 196.05 s | 56.3 % | +127.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.32 s | 5.3 % | +127.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.33 s | 4.1 % | +146.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.39 s | 3.8 % | +160.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.71 s | 3.9 % | +173.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.89 s | 4.9 % | +187.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.99 s | 4.6 % | +204.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.12 s | 4.3 % | +220.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.82 s | 4.5 % | +235.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.94 s | 5.2 % | +251.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.24 s | 4.7 % | +269.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.93 s | 4.3 % | +285.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.30 s | 3.5 % | +300.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.99 s | 3.2 % | +312.77 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +323.77 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +323.77 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +323.77 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +323.77 s |
| diarization_infer | · diarization.infer | 1 | ok | 14.20 s | 4.1 % | +323.78 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +337.98 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +337.98 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +337.98 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +338.04 s |
| queue | · asr.queue_wait | 1 | ok | 338.04 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +338.05 s |
| queue | · asr.queue_wait | 1 | ok | 338.04 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +338.05 s |
| queue | · asr.queue_wait | 1 | ok | 338.05 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +338.06 s |
| queue | · asr.queue_wait | 1 | ok | 338.05 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 2.47 s | 0.7 % | +340.20 s |
| other | notes.generate | 1 | ok | 5.47 s | — | +342.67 s |
| llm_call | · llm.note_write | 1 | ok | 5.37 s | 1.5 % | +342.73 s |

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
| lid.recording | 90.00 s | 9.44 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 8.91 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 8.29 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 9.13 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 9.94 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 8.47 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 8.34 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 14.76 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 8.57 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 9.27 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 8.40 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 9.09 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 10.11 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 18.31 s | 2.075 |
| asr.chunk | faster_whisper | 8.92 s | 14.33 s | 1.606 |
| asr.chunk | faster_whisper | 5.85 s | 13.39 s | 2.288 |
| asr.chunk | faster_whisper | 9.95 s | 13.71 s | 1.378 |
| asr.chunk | faster_whisper | 8.16 s | 16.89 s | 2.070 |
| asr.chunk | faster_whisper | 9.63 s | 15.99 s | 1.661 |
| asr.chunk | faster_whisper | 5.85 s | 15.12 s | 2.583 |
| asr.chunk | faster_whisper | 9.88 s | 15.81 s | 1.600 |
| asr.chunk | faster_whisper | 7.04 s | 17.94 s | 2.549 |
| asr.chunk | faster_whisper | 9.63 s | 16.24 s | 1.687 |
| asr.chunk | faster_whisper | 8.35 s | 14.93 s | 1.788 |
| asr.chunk | faster_whisper | 3.64 s | 12.30 s | 3.374 |
| asr.chunk | faster_whisper | 1.93 s | 10.98 s | 5.689 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 14.20 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 2.46 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.37 s | 1,820 | 0 | 0 | 293 | — (not_supported) |
| **total** |  | 2 |  |  | 7.83 s | 1,832 | 0 | 0 | 299 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,977,460,224 B (2.77 GiB) → 2,973,904,896 B (2.77 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.30 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
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

- Top critical-path stages: asr_primary 196.05 s (56.3 %); language_detection 122.72 s (35.2 %); diarization_infer 14.20 s (4.1 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
