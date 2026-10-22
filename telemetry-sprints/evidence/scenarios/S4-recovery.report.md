# Diagnostics — recording ae8bafef-7b45-4e09-82a7-47a07e8da12d

Run `2fa8e087-5acd-46b2-a035-1b4144bf5c1c` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ae8bafef-7b45-4e09-82a7-47a07e8da12d |
| processing_run_id | 2fa8e087-5acd-46b2-a035-1b4144bf5c1c |
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
| processing_wall_seconds | 297.03 s |
| rtf | 2.475 |
| speedup | 0.404 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.50 s | 0.2 % | -0.53 s |
| capture_input | asr.submit.probe | 1 | ok | 0.27 s | 0.1 % | -0.43 s |
| other | worker_job | 1 | ok | 272.79 s | — | +24.24 s |
| queue | · asr.queue_wait | 1 | ok | 24.23 s | 8.2 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.67 s | 0.2 % | +24.28 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +24.95 s |
| model_init | · vad.model | 1 | ok | 3.10 s | 1.0 % | +24.95 s |
| vad | · vad.speech_runs | 1 | ok | 5.71 s | 1.9 % | +28.05 s |
| language_detection | · lid.run | 1 | ok | 11.48 s | 3.9 % | +33.77 s |
| language_detection | · lid.run | 1 | ok | 10.97 s | 3.7 % | +45.27 s |
| language_detection | · lid.run | 1 | ok | 10.22 s | 3.4 % | +56.26 s |
| language_detection | · lid.run | 1 | ok | 10.24 s | 3.4 % | +66.48 s |
| language_detection | · lid.run | 1 | ok | 10.79 s | 3.6 % | +76.72 s |
| language_detection | · lid.run | 1 | ok | 9.95 s | 3.3 % | +87.52 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 171.68 s | 57.8 % | +97.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.73 s | 10.0 % | +97.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 25.08 s | 8.4 % | +127.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.78 s | 4.6 % | +152.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.75 s | 4.6 % | +166.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.69 s | 4.3 % | +179.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.12 s | 5.1 % | +192.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 45.19 s | 15.2 % | +207.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.25 s | 5.5 % | +252.90 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +269.16 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +269.19 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.01 s | 0.0 % | +279.79 s |
| diarization_load | · diarization.load | 1 | ok | 3.93 s | 1.3 % | +279.81 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.20 s | 4.4 % | +283.73 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +296.93 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +296.94 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +296.94 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +297.05 s |
| queue | · asr.queue_wait | 1 | ok | 297.04 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +297.06 s |
| queue | · asr.queue_wait | 1 | ok | 297.05 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +297.06 s |
| queue | · asr.queue_wait | 1 | ok | 297.06 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +297.07 s |
| queue | · asr.queue_wait | 1 | ok | 297.06 s | — | +0.01 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 91.43 s | 8 | 1.18 s | 4.66 s | 30.00 s |

### Language checks

Language checks: 6.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 25.85 s | 11.48 s | en | en 0.978, cy 0.011, nn 0.004 |
| lid.run | 21.08 s | 10.97 s | en | en 0.953, cy 0.029, nn 0.006 |
| lid.run | 2.14 s | 10.22 s | en | en 0.975, nn 0.007, cy 0.005 |
| lid.run | 4.51 s | 10.24 s | en | en 0.989, de 0.001, es 0.001 |
| lid.run | 30.00 s | 10.79 s | en | en 0.999, cy 0.001, es 0.000 |
| lid.run | 4.81 s | 9.95 s | en | en 0.997, cy 0.001, nn 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 25.85 s | 29.72 s | 1.150 |
| asr.chunk | faster_whisper | 21.08 s | 25.08 s | 1.190 |
| asr.chunk | faster_whisper | 2.14 s | 13.78 s | 6.440 |
| asr.chunk | faster_whisper | 1.85 s | 13.75 s | 7.422 |
| asr.chunk | faster_whisper | 1.18 s | 12.69 s | 10.754 |
| asr.chunk | faster_whisper | 4.51 s | 15.12 s | 3.353 |
| asr.chunk | faster_whisper | 30.00 s | 45.18 s | 1.506 |
| asr.chunk | faster_whisper | 4.81 s | 16.25 s | 3.376 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 91.43 s |
| audio duration | 120.00 s |
| reprocessing ratio | 0.762 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.93 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 13.20 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 11.7 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,455,379,968 B (2.29 GiB) → 2,389,192,704 B (2.23 GiB) |
| swap used | 1,252,253,696 B (1.17 GiB) → 1,238,638,592 B (1.15 GiB) |
| memory pressure | some_avg10=0.09 → some_avg10=0.90 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.55 s |
| telemetry buffer peak | 953 B |

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

- Top critical-path stages: asr_primary 171.69 s (57.8 %); language_detection 63.66 s (21.4 %); queue 24.23 s (8.2 %).
- Reprocessing ratio: 0.762.
- Cold loads: vad.model 3.10 s; diarization.load 3.93 s.
- Queue wait: 24.23 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
