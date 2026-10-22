# Diagnostics — recording ecc56624-64b5-4173-8550-b33d1fcce977

Run `f4eefbfc-3459-43fb-b5ed-95b6303e03a3` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ecc56624-64b5-4173-8550-b33d1fcce977 |
| processing_run_id | f4eefbfc-3459-43fb-b5ed-95b6303e03a3 |
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
| audio duration | 141.80 s |
| processing_wall_seconds | 319.15 s |
| rtf | 2.251 |
| speedup | 0.444 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 1.25 s | 0.4 % | -1.26 s |
| capture_input | asr.submit.probe | 1 | ok | 0.43 s | 0.1 % | -0.98 s |
| other | worker_job | 1 | ok | 305.00 s | — | +14.13 s |
| queue | · asr.queue_wait | 1 | ok | 14.12 s | 4.4 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.00 s | 0.3 % | +14.14 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +15.15 s |
| model_init | · vad.model | 1 | ok | 2.69 s | 0.8 % | +15.15 s |
| vad | · vad.speech_runs | 1 | ok | 3.92 s | 1.2 % | +17.84 s |
| language_detection | · lid.run | 1 | ok | 9.86 s | 3.1 % | +21.76 s |
| language_detection | · lid.run | 1 | ok | 9.45 s | 3.0 % | +31.63 s |
| language_detection | · lid.run | 1 | ok | 9.74 s | 3.1 % | +41.08 s |
| language_detection | · lid.run | 1 | ok | 9.66 s | 3.0 % | +50.83 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 2.9 % | +60.49 s |
| language_detection | · lid.run | 1 | ok | 9.25 s | 2.9 % | +69.63 s |
| language_detection | · lid.run | 1 | ok | 9.04 s | 2.8 % | +78.88 s |
| language_detection | · lid.run | 1 | ok | 9.30 s | 2.9 % | +87.93 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 198.70 s | 62.3 % | +97.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.16 s | 6.9 % | +97.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.30 s | 3.9 % | +119.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.25 s | 5.1 % | +131.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.31 s | 6.4 % | +147.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 53.61 s | 16.8 % | +168.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 26.50 s | 8.3 % | +221.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 30.88 s | 9.7 % | +248.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.63 s | 5.2 % | +279.30 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +295.95 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +295.99 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +296.00 s |
| diarization_load | · diarization.load | 1 | ok | 3.91 s | 1.2 % | +296.00 s |
| diarization_infer | · diarization.infer | 1 | ok | 19.10 s | 6.0 % | +299.91 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +319.01 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +319.02 s |
| persist | · asr.persist | 1 | ok | 0.10 s | 0.0 % | +319.04 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 136.94 s | 8 | 4.71 s | 19.26 s | 28.70 s |

### Language checks

Language checks: 8.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 9.86 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 9.45 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 9.74 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 22.49 s | 9.66 s | de | de 0.997, en 0.002, es 0.000 |
| lid.run | 28.70 s | 9.14 s | en | en 0.985, cy 0.008, zh 0.001 |
| lid.run | 19.71 s | 9.25 s | en | en 0.996, cy 0.002, zh 0.001 |
| lid.run | 18.81 s | 9.04 s | en | en 0.970, cy 0.018, nn 0.003 |
| lid.run | 4.71 s | 9.30 s | en | en 0.942, nn 0.015, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 22.16 s | 0.961 |
| asr.chunk | faster_whisper | 5.08 s | 12.30 s | 2.419 |
| asr.chunk | faster_whisper | 14.36 s | 16.25 s | 1.131 |
| asr.chunk | faster_whisper | 22.49 s | 20.31 s | 0.903 |
| asr.chunk | faster_whisper | 28.70 s | 53.60 s | 1.868 |
| asr.chunk | faster_whisper | 19.71 s | 26.50 s | 1.345 |
| asr.chunk | faster_whisper | 18.81 s | 30.88 s | 1.641 |
| asr.chunk | faster_whisper | 4.71 s | 16.63 s | 3.529 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 136.94 s |
| audio duration | 141.80 s |
| reprocessing ratio | 0.966 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.91 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 19.10 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 6.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,435,448,832 B (2.27 GiB) → 2,333,835,264 B (2.17 GiB) |
| swap used | 50,044,928 B (0.05 GiB) → 343,494,656 B (0.32 GiB) |
| memory pressure | some_avg10=0.13 → some_avg10=0.39 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 1.03 s |
| telemetry buffer peak | 1,150 B |

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

- Top critical-path stages: asr_primary 198.72 s (62.3 %); language_detection 75.43 s (23.6 %); diarization_infer 19.11 s (6.0 %).
- Reprocessing ratio: 0.966.
- Cold loads: vad.model 2.69 s; diarization.load 3.91 s.
- Queue wait: 14.12 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Hypothesis: ASR dominates (rtf 2.251, asr_primary 62.3 % of wall); consider a smaller model, quantization or a lower beam.

Checked, did not fire: `asr_device_configured`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
