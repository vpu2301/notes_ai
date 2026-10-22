# Diagnostics — recording 30f4302c-4dc2-4de3-a476-e4466b70c963

Run `8bdd3514-e8f7-4bfd-b4dc-ba8fc33203bc` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 30f4302c-4dc2-4de3-a476-e4466b70c963 |
| processing_run_id | 8bdd3514-e8f7-4bfd-b4dc-ba8fc33203bc |
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
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 120.00 s |
| processing_wall_seconds | 678.49 s |
| rtf | 5.654 |
| speedup | 0.177 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.24 s | 0.0 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.12 s | 0.0 % | -0.21 s |
| other | worker_job | 1 | ok | 389.85 s | — | +288.65 s |
| queue | · asr.queue_wait | 1 | ok | 288.64 s | 42.5 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.27 s | 0.0 % | +288.65 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +288.92 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +288.92 s |
| vad | · vad.speech_runs | 1 | ok | 4.89 s | 0.7 % | +288.92 s |
| language_detection | · lid.run | 1 | ok | 11.52 s | 1.7 % | +293.82 s |
| language_detection | · lid.run | 1 | ok | 9.42 s | 1.4 % | +305.35 s |
| language_detection | · lid.run | 1 | ok | 12.18 s | 1.8 % | +314.77 s |
| language_detection | · lid.run | 1 | ok | 10.39 s | 1.5 % | +326.96 s |
| language_detection | · lid.run | 1 | ok | 11.55 s | 1.7 % | +337.36 s |
| language_detection | · lid.run | 1 | ok | 10.29 s | 1.5 % | +348.92 s |
| language_detection | · lid.run | 1 | ok | 10.48 s | 1.5 % | +359.22 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 291.56 s | 43.0 % | +369.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 46.58 s | 6.9 % | +369.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 38.38 s | 5.7 % | +416.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.58 s | 6.1 % | +454.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 76.21 s | 11.2 % | +496.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 40.72 s | 6.0 % | +572.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 28.99 s | 4.3 % | +613.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.96 s | 2.8 % | +642.29 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +661.26 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| diarization_infer | · diarization.infer | 1 | ok | 17.12 s | 2.5 % | +661.27 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +678.40 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +678.41 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +678.41 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +678.51 s |
| queue | · asr.queue_wait | 1 | ok | 678.51 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +678.52 s |
| queue | · asr.queue_wait | 1 | ok | 678.51 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +678.52 s |
| queue | · asr.queue_wait | 1 | ok | 678.52 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +678.52 s |
| queue | · asr.queue_wait | 1 | ok | 678.52 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +678.53 s |
| queue | · asr.queue_wait | 1 | ok | 678.53 s | — | +0.00 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 115.72 s | 7 | 4.73 s | 18.81 s | 29.98 s |

### Language checks

Language checks: 7.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 11.52 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 9.42 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 12.18 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 10.39 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 11.55 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 10.29 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 10.48 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 46.57 s | 2.019 |
| asr.chunk | faster_whisper | 5.08 s | 38.37 s | 7.548 |
| asr.chunk | faster_whisper | 14.36 s | 41.58 s | 2.895 |
| asr.chunk | faster_whisper | 29.98 s | 76.21 s | 2.542 |
| asr.chunk | faster_whisper | 19.68 s | 40.72 s | 2.069 |
| asr.chunk | faster_whisper | 18.81 s | 28.99 s | 1.541 |
| asr.chunk | faster_whisper | 4.73 s | 18.96 s | 4.004 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 115.72 s |
| audio duration | 120.00 s |
| reprocessing ratio | 0.964 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 17.12 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,989,780,992 B (2.78 GiB) → 2,371,092,480 B (2.21 GiB) |
| swap used | 1,277,227,008 B (1.19 GiB) → 1,268,621,312 B (1.18 GiB) |
| memory pressure | some_avg10=0.35 → some_avg10=0.54 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.56 s |
| telemetry buffer peak | 1,560 B |

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

- Top critical-path stages: asr_primary 291.56 s (43.0 %); queue 288.64 s (42.5 %); language_detection 75.82 s (11.2 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 288.64 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
