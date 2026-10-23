# Diagnostics — recording f903a7f9-c637-43d2-bb13-00b0457e05ff

Run `da490357-3508-4449-84fb-f43dfff7fc2f` · initial · cancelled

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | f903a7f9-c637-43d2-bb13-00b0457e05ff |
| processing_run_id | da490357-3508-4449-84fb-f43dfff7fc2f |
| kind | initial |
| trigger | user |
| status | cancelled |
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
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 892.39 s |
| processing_wall_seconds | 434.53 s |
| rtf | 0.487 |
| speedup | 2.054 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.18 s | 0.0 % | -0.19 s |
| capture_input | asr.submit.probe | 1 | ok | 0.06 s | 0.0 % | -0.13 s |
| other | worker_job | 1 | cancelled | 424.31 s | — | +10.22 s |
| queue | · asr.queue_wait | 1 | ok | 10.21 s | 2.4 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.84 s | 0.2 % | +10.22 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +11.06 s |
| model_init | · vad.model | 1 | ok | 1.38 s | 0.3 % | +11.06 s |
| vad | · vad.speech_runs | 1 | ok | 23.62 s | 5.4 % | +12.45 s |
| language_detection | · lid.recording | 1 | ok | 5.39 s | 1.2 % | +36.08 s |
| language_detection | · lid.run | 1 | ok | 4.72 s | 1.1 % | +41.47 s |
| language_detection | · lid.run | 1 | ok | 4.74 s | 1.1 % | +46.18 s |
| language_detection | · lid.run | 1 | ok | 4.92 s | 1.1 % | +50.93 s |
| language_detection | · lid.run | 1 | ok | 4.60 s | 1.1 % | +55.85 s |
| language_detection | · lid.run | 1 | ok | 4.63 s | 1.1 % | +60.45 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 1.1 % | +65.08 s |
| language_detection | · lid.run | 1 | ok | 4.59 s | 1.1 % | +69.78 s |
| language_detection | · lid.run | 1 | ok | 4.80 s | 1.1 % | +74.37 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 1.2 % | +79.17 s |
| language_detection | · lid.run | 1 | ok | 4.84 s | 1.1 % | +84.26 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 1.1 % | +89.10 s |
| language_detection | · lid.run | 1 | ok | 5.13 s | 1.2 % | +93.93 s |
| language_detection | · lid.run | 1 | ok | 4.96 s | 1.1 % | +99.06 s |
| language_detection | · lid.run | 1 | ok | 5.61 s | 1.3 % | +104.03 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 1.3 % | +109.64 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 1.2 % | +115.11 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 1.2 % | +120.46 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 1.3 % | +125.86 s |
| language_detection | · lid.run | 1 | ok | 6.05 s | 1.4 % | +131.49 s |
| language_detection | · lid.run | 1 | ok | 6.08 s | 1.4 % | +137.55 s |
| language_detection | · lid.run | 1 | ok | 6.37 s | 1.5 % | +143.63 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 1.4 % | +150.00 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 1.4 % | +156.07 s |
| language_detection | · lid.run | 1 | ok | 6.21 s | 1.4 % | +162.14 s |
| language_detection | · lid.run | 1 | ok | 6.09 s | 1.4 % | +168.36 s |
| language_detection | · lid.run | 1 | ok | 6.24 s | 1.4 % | +174.45 s |
| language_detection | · lid.run | 1 | ok | 6.11 s | 1.4 % | +180.70 s |
| language_detection | · lid.run | 1 | ok | 6.28 s | 1.4 % | +186.81 s |
| language_detection | · lid.run | 1 | ok | 6.36 s | 1.5 % | +193.08 s |
| language_detection | · lid.run | 1 | ok | 6.32 s | 1.5 % | +199.45 s |
| language_detection | · lid.run | 1 | ok | 6.22 s | 1.4 % | +205.78 s |
| language_detection | · lid.run | 1 | ok | 6.17 s | 1.4 % | +212.00 s |
| language_detection | · lid.run | 1 | ok | 5.83 s | 1.3 % | +218.18 s |
| language_detection | · lid.run | 1 | ok | 5.99 s | 1.4 % | +224.01 s |
| language_detection | · lid.run | 1 | ok | 6.12 s | 1.4 % | +230.00 s |
| language_detection | · lid.run | 1 | ok | 5.91 s | 1.4 % | +236.12 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 1.4 % | +242.03 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 1.3 % | +248.00 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 1.3 % | +253.67 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 1.3 % | +259.30 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 1.3 % | +264.88 s |
| language_detection | · lid.run | 1 | ok | 5.60 s | 1.3 % | +270.51 s |
| language_detection | · lid.run | 1 | ok | 5.89 s | 1.4 % | +276.11 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 1.3 % | +282.00 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 1.3 % | +287.55 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 1.3 % | +293.19 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 1.3 % | +298.85 s |
| language_detection | · lid.run | 1 | ok | 16.07 s | 3.7 % | +304.35 s |
| language_detection | · lid.run | 1 | ok | 23.54 s | 5.4 % | +320.43 s |
| language_detection | · lid.run | 1 | ok | 17.83 s | 4.1 % | +343.98 s |
| language_detection | · lid.run | 1 | ok | 10.86 s | 2.5 % | +361.82 s |
| language_detection | · lid.run | 1 | ok | 9.93 s | 2.3 % | +372.70 s |
| language_detection | · lid.run | 1 | ok | 9.72 s | 2.2 % | +382.63 s |
| language_detection | · lid.run | 1 | ok | 10.49 s | 2.4 % | +392.36 s |
| language_detection | · lid.run | 1 | ok | 9.89 s | 2.3 % | +402.85 s |
| language_detection | · lid.run | 1 | ok | 10.11 s | 2.3 % | +412.75 s |
| language_detection | · lid.run | 1 | ok | 11.63 s | 2.7 % | +422.87 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 798.08 s | 82 | 1.28 s | 8.68 s | 30.00 s |

### Language checks

Language checks: 58.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 5.39 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 4.72 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 4.74 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 4.92 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 4.60 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 4.63 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 4.69 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 4.59 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 4.80 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.08 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 4.84 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 4.83 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.13 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 4.96 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.61 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 5.47 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.36 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.39 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.63 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 6.05 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 6.08 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 6.37 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 6.07 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 6.07 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 6.21 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 6.09 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 6.24 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 6.11 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 6.28 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 6.36 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 6.32 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 6.22 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 6.17 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 5.83 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 5.99 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 6.12 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.91 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 5.97 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 5.66 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.63 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 5.58 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 5.62 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 5.60 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 5.89 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 5.55 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 5.63 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.66 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.50 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 16.07 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 23.54 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 17.83 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 10.86 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 9.93 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 9.72 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 10.49 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 9.89 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 10.11 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 11.63 s | en | en 0.997, nn 0.001, cy 0.000 |

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 892.39 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,455,875,584 B (2.29 GiB) → 2,845,757,440 B (2.65 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.12 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.43 s |
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
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: language_detection 398.24 s (91.6 %); vad 23.62 s (5.4 %); queue 10.21 s (2.4 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: vad.model 1.38 s.
- Queue wait: 10.21 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `cold_model_init`, `swap_growth`.
