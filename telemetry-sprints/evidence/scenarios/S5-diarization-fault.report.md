# Diagnostics — recording 4a390264-ce5a-4ceb-ab69-4d4aafb659f1

Run `2d702613-5630-476d-b7cf-e9d17247b8a9` · initial · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 4a390264-ce5a-4ceb-ab69-4d4aafb659f1 |
| processing_run_id | 2d702613-5630-476d-b7cf-e9d17247b8a9 |
| kind | initial |
| trigger | user |
| status | failed |
| error category | diarization |
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
| processing_wall_seconds | 304.88 s |
| rtf | 2.541 |
| speedup | 0.394 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.49 s | 0.2 % | -0.53 s |
| capture_input | asr.submit.probe | 1 | ok | 0.21 s | 0.1 % | -0.37 s |
| other | worker_job | 1 | error | 280.34 s | — | +24.56 s |
| queue | · asr.queue_wait | 1 | ok | 24.53 s | 8.0 % | +0.03 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.65 s | 0.2 % | +24.57 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +25.22 s |
| model_init | · vad.model | 1 | ok | 2.66 s | 0.9 % | +25.23 s |
| vad | · vad.speech_runs | 1 | ok | 5.15 s | 1.7 % | +27.89 s |
| language_detection | · lid.run | 1 | ok | 11.43 s | 3.7 % | +33.04 s |
| language_detection | · lid.run | 1 | ok | 10.35 s | 3.4 % | +44.47 s |
| language_detection | · lid.run | 1 | ok | 10.59 s | 3.5 % | +54.83 s |
| language_detection | · lid.run | 1 | ok | 11.26 s | 3.7 % | +65.43 s |
| language_detection | · lid.run | 1 | ok | 10.80 s | 3.5 % | +76.70 s |
| language_detection | · lid.run | 1 | ok | 10.76 s | 3.5 % | +87.50 s |
| language_detection | · lid.run | 1 | ok | 11.62 s | 3.8 % | +98.27 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 191.06 s | 62.7 % | +109.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 28.45 s | 9.3 % | +109.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.56 s | 5.1 % | +138.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 26.05 s | 8.5 % | +153.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 50.77 s | 16.7 % | +180.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 30.21 s | 9.9 % | +230.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.18 s | 7.6 % | +261.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.71 s | 5.5 % | +284.23 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +300.96 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +301.00 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +301.00 s |
| diarization_load | · diarization.load | 1 | ok | 3.88 s | 1.3 % | +301.00 s |
| diarization_infer | · diarization.infer | 1 | error | 0.00 s | 0.0 % | +304.87 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +304.90 s |
| queue | · asr.queue_wait | 1 | ok | 304.87 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +304.91 s |
| queue | · asr.queue_wait | 1 | ok | 304.88 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +304.91 s |
| queue | · asr.queue_wait | 1 | ok | 304.89 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +304.92 s |
| queue | · asr.queue_wait | 1 | ok | 304.89 s | — | +0.03 s |

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
| lid.run | 23.07 s | 11.43 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 10.35 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.59 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 11.26 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 10.80 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 10.76 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 11.62 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 28.45 s | 1.233 |
| asr.chunk | faster_whisper | 5.08 s | 15.56 s | 3.061 |
| asr.chunk | faster_whisper | 14.36 s | 26.05 s | 1.814 |
| asr.chunk | faster_whisper | 29.98 s | 50.77 s | 1.693 |
| asr.chunk | faster_whisper | 19.68 s | 30.21 s | 1.535 |
| asr.chunk | faster_whisper | 18.81 s | 23.18 s | 1.232 |
| asr.chunk | faster_whisper | 4.73 s | 16.71 s | 3.530 |

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
| load | ok | 3.88 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | error | — | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,455,474,176 B (2.29 GiB) → 3,296,903,168 B (3.07 GiB) |
| swap used | 1,254,141,952 B (1.17 GiB) → 1,252,560,896 B (1.17 GiB) |
| memory pressure | some_avg10=0.13 → some_avg10=0.27 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.35 s |
| telemetry buffer peak | 1,142 B |

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
- **diarization_infer**
  - diarization.infer: `infer_seconds` (not_measured)
  - diarization.infer: `speakers_detected` (not_measured)
  - diarization.infer: `unknown_speaker_share` (not_measured)
- **diarization_load**
  - diarization.load: `speakers_detected` (not_applicable)
  - diarization.load: `unknown_speaker_share` (not_applicable)
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **run**
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 191.06 s (62.7 %); language_detection 76.80 s (25.2 %); queue 24.53 s (8.0 %).
- Reprocessing ratio: 0.964.
- Cold loads: vad.model 2.66 s; diarization.load 3.88 s.
- Queue wait: 24.53 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Hypothesis: ASR dominates (rtf 2.541, asr_primary 62.7 % of wall); consider a smaller model, quantization or a lower beam.
- Not assessable: unknown_speaker_share unavailable (not_measured) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `reprocessing`, `cold_model_init`, `swap_growth`.
