# Diagnostics — recording 6a8eb711-5fa7-4118-809f-07e3dd6357e9

Run `4ebf385d-a0ef-4c02-af60-95329b2f191f` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 6a8eb711-5fa7-4118-809f-07e3dd6357e9 |
| processing_run_id | 4ebf385d-a0ef-4c02-af60-95329b2f191f |
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
| processing_wall_seconds | 402.70 s |
| rtf | 3.537 |
| speedup | 0.283 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.23 s | 0.1 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.14 s | 0.0 % | -0.21 s |
| other | worker_job | 1 | ok | 368.77 s | — | +27.10 s |
| queue | · asr.queue_wait | 1 | ok | 27.08 s | 6.7 % | +0.02 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.84 s | 0.2 % | +27.11 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +27.96 s |
| model_init | · vad.model | 1 | ok | 3.03 s | 0.8 % | +27.96 s |
| vad | · vad.speech_runs | 1 | ok | 4.38 s | 1.1 % | +30.98 s |
| language_detection | · lid.recording | 1 | ok | 10.27 s | 2.6 % | +35.37 s |
| language_detection | · lid.run | 1 | ok | 9.55 s | 2.4 % | +45.64 s |
| language_detection | · lid.run | 1 | ok | 11.43 s | 2.8 % | +55.21 s |
| language_detection | · lid.run | 1 | ok | 9.33 s | 2.3 % | +66.64 s |
| language_detection | · lid.run | 1 | ok | 8.89 s | 2.2 % | +75.97 s |
| language_detection | · lid.run | 1 | ok | 10.58 s | 2.6 % | +84.87 s |
| language_detection | · lid.run | 1 | ok | 8.55 s | 2.1 % | +95.45 s |
| language_detection | · lid.run | 1 | ok | 9.79 s | 2.4 % | +104.00 s |
| language_detection | · lid.run | 1 | ok | 8.72 s | 2.2 % | +113.81 s |
| language_detection | · lid.run | 1 | ok | 9.09 s | 2.3 % | +122.53 s |
| language_detection | · lid.run | 1 | ok | 9.55 s | 2.4 % | +131.62 s |
| language_detection | · lid.run | 1 | ok | 9.37 s | 2.3 % | +141.17 s |
| language_detection | · lid.run | 1 | ok | 9.42 s | 2.3 % | +150.55 s |
| language_detection | · lid.run | 1 | ok | 8.95 s | 2.2 % | +159.97 s |
| language_detection | · lid.run | 1 | ok | 9.20 s | 2.3 % | +168.93 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 200.38 s | 49.8 % | +178.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.23 s | 3.5 % | +178.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.30 s | 3.3 % | +192.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.04 s | 4.2 % | +205.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.66 s | 3.6 % | +222.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.95 s | 4.2 % | +237.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.00 s | 3.5 % | +254.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.55 s | 3.6 % | +268.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.77 s | 2.9 % | +282.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.11 s | 3.3 % | +294.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.76 s | 3.2 % | +307.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.29 s | 4.5 % | +320.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.17 s | 3.8 % | +338.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.15 s | 3.0 % | +354.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.27 s | 3.0 % | +366.21 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +378.51 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +378.55 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +378.56 s |
| diarization_load | · diarization.load | 1 | ok | 3.78 s | 0.9 % | +378.56 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.43 s | 3.3 % | +382.34 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +395.77 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +395.78 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +395.79 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.89 s |
| queue | · asr.queue_wait | 1 | ok | 395.88 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.90 s |
| queue | · asr.queue_wait | 1 | ok | 395.88 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.91 s |
| queue | · asr.queue_wait | 1 | ok | 395.89 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.92 s |
| queue | · asr.queue_wait | 1 | ok | 395.90 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.92 s |
| queue | · asr.queue_wait | 1 | ok | 395.91 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +395.93 s |
| queue | · asr.queue_wait | 1 | ok | 395.91 s | — | +0.02 s |
| llm_call | llm.provider_probe | 1 | ok | 0.65 s | 0.2 % | +397.18 s |
| other | notes.generate | 1 | ok | 4.86 s | — | +397.84 s |
| llm_call | · llm.note_write | 1 | ok | 4.65 s | 1.2 % | +398.01 s |

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
| lid.recording | 90.00 s | 10.27 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 9.55 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 11.43 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 9.33 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 8.89 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 10.58 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 8.55 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 9.79 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 8.72 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 9.09 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 9.55 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 9.37 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 9.42 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 8.95 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 9.20 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 14.22 s | 2.213 |
| asr.chunk | faster_whisper | 7.23 s | 13.30 s | 1.840 |
| asr.chunk | faster_whisper | 6.88 s | 17.04 s | 2.479 |
| asr.chunk | faster_whisper | 6.75 s | 14.66 s | 2.172 |
| asr.chunk | faster_whisper | 7.26 s | 16.95 s | 2.334 |
| asr.chunk | faster_whisper | 7.93 s | 14.00 s | 1.765 |
| asr.chunk | faster_whisper | 8.86 s | 14.55 s | 1.642 |
| asr.chunk | faster_whisper | 5.31 s | 11.77 s | 2.218 |
| asr.chunk | faster_whisper | 5.34 s | 13.11 s | 2.454 |
| asr.chunk | faster_whisper | 5.79 s | 12.76 s | 2.204 |
| asr.chunk | faster_whisper | 17.12 s | 18.29 s | 1.068 |
| asr.chunk | faster_whisper | 8.38 s | 15.17 s | 1.810 |
| asr.chunk | faster_whisper | 4.73 s | 12.15 s | 2.567 |
| asr.chunk | faster_whisper | 2.83 s | 12.27 s | 4.327 |

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
| load | ok | 3.78 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 13.43 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.65 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.65 s | 1,764 | 0 | 0 | 322 | — (not_supported) |
| **total** |  | 2 |  |  | 5.30 s | 1,776 | 0 | 0 | 328 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,571,904 B (2.29 GiB) → 3,031,822,336 B (2.82 GiB) |
| swap used | 1,316,188,160 B (1.23 GiB) → 1,324,044,288 B (1.23 GiB) |
| memory pressure | some_avg10=0.15 → some_avg10=1.03 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.03 s |
| telemetry buffer peak | 1,179 B |

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

- Top critical-path stages: asr_primary 200.38 s (49.8 %); language_detection 142.69 s (35.4 %); queue 27.08 s (6.7 %).
- Reprocessing ratio: 0.886.
- Cold loads: vad.model 3.03 s; diarization.load 3.78 s.
- Queue wait: 27.08 s.
- LLM latency share of wall: 1.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
