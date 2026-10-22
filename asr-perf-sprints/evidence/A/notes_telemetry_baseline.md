# Notes AI — pipeline telemetry

Collected 2026-10-22 15:24 UTC from the dev stack: 19 stored processing runs, all workspaces. Timings, counts, backends and devices only — no transcript, note or prompt text.

## Overview

| Metric | Value |
|---|---|
| runs | 19 |
| succeeded | 11 |
| partial | 1 |
| failed | 5 |
| cancelled | 1 |
| running | 1 |
| rtf p50 / p95 | 2.532 / 40.987 (n=13) |
| user wait p50 / p95 | — s / — s (n=0) |
| telemetry overhead (median) | 0.189 s |

### Mean share of wall time per stage (critical path)

| Stage | Share |
|---|---|
| asr_primary | 23.6 % |
| queue | 14.4 % |
| language_detection | 13.9 % |
| llm_call | 13.4 % |
| model_init | 5.0 % |
| vad | 3.3 % |
| upload | 2.2 % |
| diarization_infer | 1.9 % |
| audio_prep | 1.5 % |
| capture_input | 0.7 % |
| diarization_load | 0.4 % |
| persist | 0.0 % |
| postprocess_cleanup | 0.0 % |
| postprocess_attribute | 0.0 % |

### Backends and devices

| Kind | Backend / model | Device | Source | Runs |
|---|---|---|---|---|
| asr | inproc_cpu_asr | cpu | observed | 11 |
| asr | — | cpu | observed | 3 |
| diarization | legacy-ecapa-ahc | cpu | configured | 10 |
| diarization | — | cpu | configured | 4 |
| llm | mistral-large-2512 | — | configured | 7 |
| llm | notes-chat | — | configured | 3 |

## Runs

| Submitted (UTC) | Recording | Run | Kind | Status | Audio | Wall | rtf | User wait |
|---|---|---|---|---|---|---|---|---|
| 2026-10-22 15:07 | 7967deba | f2e27fc8 | initial | running | 900.00 s | — s | — | — |
| 2026-10-22 14:57 | bc460637 | e3290649 | initial | succeeded | 120.00 s | 537.85 s | 4.482 | — |
| 2026-10-22 14:52 | 0b07da37 | ebf66ca8 | initial | succeeded | 120.00 s | 303.82 s | 2.532 | — |
| 2026-10-22 14:50 | 64eed3a7 | 9ac0280f | reprocess (notes) | succeeded | — s | 8.71 s | — | — |
| 2026-10-22 14:47 | ecc56624 | f4eefbfc | initial | succeeded | 141.80 s | 319.15 s | 2.251 | — |
| 2026-10-22 14:46 | edf28aaa | 0d3ce71b | reprocess (notes) | succeeded | — s | 5.95 s | — | — |
| 2026-10-22 14:29 | 13697ab7 | 6c1b947a | initial | succeeded | 141.80 s | 1990.62 s | 14.038 | — |
| 2026-10-22 14:22 | ec4f4e12 | 351eccc5 | initial | cancelled | 900.00 s | 91.62 s | 0.102 | — |
| 2026-10-22 14:17 | ae8bafef | 2fa8e087 | initial | succeeded | 120.00 s | 297.03 s | 2.475 | — |
| 2026-10-22 14:11 | 4a390264 | 2d702613 | initial | failed | 120.00 s | 304.88 s | 2.541 | — |
| 2026-10-22 14:06 | 7a06a6e4 | 17846383 | initial | succeeded | 120.00 s | 324.24 s | 2.702 | — |
| 2026-10-22 14:02 | edf28aaa | a081fa3a | reprocess (notes) | failed | — s | 59.39 s | — | — |
| 2026-10-22 14:01 | 64eed3a7 | 68645c41 | reprocess (notes) | failed | — s | 55.50 s | — | — |
| 2026-10-22 13:52 | 30f4302c | 8bdd3514 | initial | succeeded | 120.00 s | 4918.44 s | 40.987 | — |
| 2026-10-22 13:52 | 64eed3a7 | e608a97d | initial | partial | 120.00 s | 521.97 s | 4.350 | — |
| 2026-10-22 13:52 | eb2040bd | 52f7bff1 | initial | failed | 120.00 s | 25.19 s | 0.210 | — |
| 2026-10-22 13:48 | 164eff6c | 2b4846f9 | initial | failed | 120.00 s | 3.56 s | 0.030 | — |
| 2026-10-22 12:32 | 78f2823c | 18e1c7b8 | reprocess (notes) | succeeded | — s | 3.69 s | — | — |
| 2026-10-22 11:44 | 78f2823c | 83d1f157 | initial | succeeded | 90.00 s | 212.82 s | 2.365 | — |

## Run reports


---

## Diagnostics — recording 7967deba-52de-45d6-a0e2-1356966ffc9c

Run `f2e27fc8-efdc-4d1f-9ffe-ffcc13065477` · initial · running

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7967deba-52de-45d6-a0e2-1356966ffc9c |
| processing_run_id | f2e27fc8-efdc-4d1f-9ffe-ffcc13065477 |
| kind | initial |
| trigger | user |
| status | running |
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
| audio duration | 900.00 s |
| processing_wall_seconds | — (not_measured) |
| rtf | — (not_measured) |
| speedup | — (not_measured) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 1.09 s | — | -1.10 s |
| capture_input | asr.submit.probe | 1 | ok | 0.24 s | — | -0.57 s |
| other | worker_job | 1 | started | — | — | +21.84 s |
| queue | · asr.queue_wait | 1 | ok | 21.83 s | — | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.50 s | — | +21.86 s |
| model_init | · asr.model | 1 | ok | 0.00 s | — | +23.37 s |
| model_init | · vad.model | 1 | ok | 2.98 s | — | +23.37 s |
| vad | · vad.speech_runs | 1 | ok | 31.55 s | — | +26.35 s |
| language_detection | · lid.run | 1 | ok | 10.88 s | — | +57.93 s |
| language_detection | · lid.run | 1 | ok | 9.77 s | — | +68.81 s |
| language_detection | · lid.run | 1 | ok | 9.50 s | — | +78.59 s |
| language_detection | · lid.run | 1 | ok | 9.66 s | — | +88.09 s |
| language_detection | · lid.run | 1 | ok | 12.68 s | — | +97.76 s |
| language_detection | · lid.run | 1 | ok | 11.33 s | — | +110.46 s |
| language_detection | · lid.run | 1 | ok | 9.78 s | — | +121.80 s |
| language_detection | · lid.run | 1 | ok | 11.68 s | — | +131.58 s |
| language_detection | · lid.run | 1 | ok | 9.84 s | — | +143.27 s |
| language_detection | · lid.run | 1 | ok | 9.70 s | — | +153.12 s |
| language_detection | · lid.run | 1 | ok | 9.86 s | — | +162.83 s |
| language_detection | · lid.run | 1 | ok | 9.81 s | — | +172.70 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | — | +182.52 s |
| language_detection | · lid.run | 1 | ok | 8.70 s | — | +191.52 s |
| language_detection | · lid.run | 1 | ok | 14.83 s | — | +200.22 s |
| language_detection | · lid.run | 1 | ok | 11.36 s | — | +215.06 s |
| language_detection | · lid.run | 1 | ok | 9.93 s | — | +226.42 s |
| language_detection | · lid.run | 1 | ok | 10.79 s | — | +236.35 s |
| language_detection | · lid.run | 1 | ok | 9.49 s | — | +247.15 s |
| language_detection | · lid.run | 1 | ok | 9.87 s | — | +256.65 s |
| language_detection | · lid.run | 1 | ok | 12.43 s | — | +266.53 s |
| language_detection | · lid.run | 1 | ok | 13.31 s | — | +278.97 s |
| language_detection | · lid.run | 1 | ok | 19.38 s | — | +292.31 s |
| language_detection | · lid.run | 1 | ok | 12.43 s | — | +311.84 s |
| language_detection | · lid.run | 1 | ok | 11.48 s | — | +324.27 s |
| language_detection | · lid.run | 1 | ok | 9.94 s | — | +335.76 s |
| language_detection | · lid.run | 1 | ok | 9.45 s | — | +345.71 s |
| language_detection | · lid.run | 1 | ok | 10.60 s | — | +355.17 s |
| language_detection | · lid.run | 1 | ok | 13.88 s | — | +365.78 s |
| language_detection | · lid.run | 1 | ok | 11.82 s | — | +379.67 s |
| language_detection | · lid.run | 1 | ok | 12.51 s | — | +391.50 s |
| language_detection | · lid.run | 1 | ok | 11.91 s | — | +404.02 s |
| language_detection | · lid.run | 1 | ok | 11.03 s | — | +415.94 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | — | +426.99 s |
| language_detection | · lid.run | 1 | ok | 11.24 s | — | +437.33 s |
| language_detection | · lid.run | 1 | ok | 10.34 s | — | +448.57 s |
| language_detection | · lid.run | 1 | ok | 11.57 s | — | +458.92 s |
| language_detection | · lid.run | 1 | ok | 11.84 s | — | +470.51 s |
| language_detection | · lid.run | 1 | ok | 11.90 s | — | +482.36 s |
| language_detection | · lid.run | 1 | ok | 10.69 s | — | +494.28 s |
| language_detection | · lid.run | 1 | ok | 11.42 s | — | +504.99 s |
| language_detection | · lid.run | 1 | ok | 9.05 s | — | +516.42 s |
| language_detection | · lid.run | 1 | ok | 11.37 s | — | +525.48 s |
| language_detection | · lid.run | 1 | ok | 9.98 s | — | +536.85 s |
| language_detection | · lid.run | 1 | ok | 11.45 s | — | +546.84 s |
| language_detection | · lid.run | 1 | ok | 11.44 s | — | +558.31 s |
| language_detection | · lid.run | 1 | ok | 10.77 s | — | +569.77 s |
| language_detection | · lid.run | 1 | ok | 12.23 s | — | +580.55 s |
| language_detection | · lid.run | 1 | ok | 10.94 s | — | +592.78 s |
| language_detection | · lid.run | 1 | ok | 9.81 s | — | +603.73 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | — | +613.54 s |
| language_detection | · lid.run | 1 | ok | 11.72 s | — | +623.28 s |
| language_detection | · lid.run | 1 | ok | 11.21 s | — | +635.01 s |
| language_detection | · lid.run | 1 | ok | 9.91 s | — | +646.22 s |
| asr_primary | · asr.transcribe_runs | 1 | started | — | — | +656.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.96 s | — | +656.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.32 s | — | +668.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.91 s | — | +685.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.66 s | — | +708.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.58 s | — | +728.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.92 s | — | +740.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.92 s | — | +757.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.27 s | — | +787.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.29 s | — | +809.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.46 s | — | +824.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.63 s | — | +835.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.44 s | — | +847.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.66 s | — | +863.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.37 s | — | +885.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.10 s | — | +907.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.53 s | — | +922.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 40.93 s | — | +939.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.74 s | — | +980.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.38 s | — | +992.05 s |
| asr_primary | · · asr.chunk | 1 | started | — | — | +1011.44 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 866.14 s | 61 | 1.12 s | 11.42 s | 30.00 s |

### Language checks

Language checks: 54.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 10.68 s | 10.88 s | en | en 0.982, cy 0.008, la 0.003 |
| lid.run | 14.91 s | 9.77 s | en | en 0.995, cy 0.003, la 0.000 |
| lid.run | 8.44 s | 9.50 s | en | en 0.996, cy 0.002, la 0.001 |
| lid.run | 2.04 s | 9.66 s | en | en 0.975, cy 0.007, nn 0.002 |
| lid.run | 4.89 s | 12.68 s | en | en 0.986, cy 0.009, la 0.001 |
| lid.run | 24.48 s | 11.33 s | en | en 0.986, cy 0.004, es 0.002 |
| lid.run | 11.23 s | 9.78 s | en | en 0.986, cy 0.008, fr 0.001 |
| lid.run | 6.88 s | 11.68 s | en | en 0.972, cy 0.010, fr 0.007 |
| lid.run | 10.43 s | 9.84 s | en | en 0.987, cy 0.005, la 0.001 |
| lid.run | 16.60 s | 9.70 s | en | en 0.974, cy 0.008, es 0.002 |
| lid.run | 17.63 s | 9.86 s | en | en 0.994, cy 0.003, pt 0.001 |
| lid.run | 7.61 s | 9.81 s | en | en 0.982, cy 0.006, es 0.002 |
| lid.run | 13.08 s | 9.00 s | en | en 0.992, cy 0.004, la 0.001 |
| lid.run | 30.00 s | 8.70 s | en | en 0.996, cy 0.002, pt 0.000 |
| lid.run | 3.95 s | 14.83 s | en | en 0.985, cy 0.006, es 0.001 |
| lid.run | 11.42 s | 11.36 s | en | en 0.975, cy 0.017, la 0.002 |
| lid.run | 3.64 s | 9.93 s | en | en 0.983, cy 0.003, nn 0.002 |
| lid.run | 30.00 s | 10.79 s | en | en 0.997, cy 0.001, fr 0.000 |
| lid.run | 3.90 s | 9.49 s | en | en 0.991, cy 0.003, nn 0.001 |
| lid.run | 30.00 s | 9.87 s | en | en 0.996, cy 0.002, pt 0.000 |
| lid.run | 20.00 s | 12.43 s | en | en 0.994, cy 0.004, la 0.000 |
| lid.run | 14.68 s | 13.31 s | en | en 0.991, cy 0.004, es 0.001 |
| lid.run | 5.08 s | 19.38 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.40 s | 12.43 s | en | en 0.976, cy 0.009, es 0.002 |
| lid.run | 29.95 s | 11.48 s | en | en 0.994, cy 0.003, fr 0.000 |
| lid.run | 19.68 s | 9.94 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 9.45 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 30.00 s | 10.60 s | en | en 0.989, cy 0.006, la 0.001 |
| lid.run | 30.00 s | 13.88 s | en | en 0.988, cy 0.007, ru 0.001 |
| lid.run | 30.00 s | 11.82 s | en | en 0.984, cy 0.008, es 0.001 |
| lid.run | 22.54 s | 12.51 s | en | en 0.992, cy 0.004, nn 0.002 |
| lid.run | 2.17 s | 11.91 s | en | en 0.980, cy 0.005, zh 0.003 |
| lid.run | 8.64 s | 11.03 s | en | en 0.990, cy 0.003, it 0.001 |
| lid.run | 21.82 s | 10.33 s | en | en 0.994, cy 0.003, fr 0.001 |
| lid.run | 15.84 s | 11.24 s | en | en 0.997, cy 0.001, nn 0.000 |
| lid.run | 30.00 s | 10.34 s | en | en 0.994, cy 0.003, zh 0.001 |
| lid.run | 30.00 s | 11.57 s | en | en 0.997, cy 0.001, zh 0.000 |
| lid.run | 30.00 s | 11.84 s | en | en 0.998, cy 0.001, es 0.000 |
| lid.run | 30.00 s | 11.90 s | en | en 0.998, cy 0.001, es 0.000 |
| lid.run | 20.44 s | 10.69 s | en | en 1.000, cy 0.000, es 0.000 |
| lid.run | 15.13 s | 11.42 s | en | en 0.989, cy 0.003, nn 0.003 |
| lid.run | 9.47 s | 9.05 s | en | en 0.981, nn 0.004, cy 0.002 |
| lid.run | 18.08 s | 11.37 s | en | en 0.984, cy 0.004, fr 0.002 |
| lid.run | 20.03 s | 9.98 s | en | en 0.995, cy 0.002, la 0.001 |
| lid.run | 6.46 s | 11.45 s | en | en 0.985, cy 0.005, nn 0.004 |
| lid.run | 4.44 s | 11.44 s | en | en 0.973, cy 0.011, nn 0.006 |
| lid.run | 3.87 s | 10.77 s | en | en 0.999, cy 0.000, nn 0.000 |
| lid.run | 30.00 s | 12.23 s | en | en 0.997, cy 0.002, nn 0.000 |
| lid.run | 10.80 s | 10.94 s | en | en 0.985, nn 0.004, cy 0.003 |
| lid.run | 8.28 s | 9.81 s | en | en 0.974, cy 0.010, fr 0.004 |
| lid.run | 29.34 s | 9.71 s | en | en 0.995, cy 0.003, es 0.000 |
| lid.run | 2.17 s | 11.72 s | en | en 0.984, cy 0.007, nn 0.003 |
| lid.run | 2.08 s | 11.21 s | en | en 0.957, cy 0.013, nn 0.007 |
| lid.run | 9.15 s | 9.91 s | en | en 0.946, cy 0.029, nn 0.009 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 1.85 s | 11.96 s | 6.457 |
| asr.chunk | faster_whisper | 10.68 s | 17.32 s | 1.621 |
| asr.chunk | faster_whisper | 14.91 s | 22.90 s | 1.536 |
| asr.chunk | faster_whisper | 8.44 s | 19.65 s | 2.327 |
| asr.chunk | faster_whisper | 2.04 s | 12.58 s | 6.156 |
| asr.chunk | faster_whisper | 4.89 s | 16.92 s | 3.458 |
| asr.chunk | faster_whisper | 24.48 s | 29.92 s | 1.222 |
| asr.chunk | faster_whisper | 11.23 s | 22.27 s | 1.983 |
| asr.chunk | faster_whisper | 6.88 s | 14.29 s | 2.078 |
| asr.chunk | faster_whisper | 1.40 s | 11.46 s | 8.161 |
| asr.chunk | faster_whisper | 1.63 s | 11.63 s | 7.143 |
| asr.chunk | faster_whisper | 10.43 s | 16.44 s | 1.577 |
| asr.chunk | faster_whisper | 16.60 s | 21.66 s | 1.305 |
| asr.chunk | faster_whisper | 17.63 s | 22.37 s | 1.269 |
| asr.chunk | faster_whisper | 7.61 s | 15.10 s | 1.984 |
| asr.chunk | faster_whisper | 13.08 s | 16.53 s | 1.263 |
| asr.chunk | faster_whisper | 30.00 s | 40.93 s | 1.364 |
| asr.chunk | faster_whisper | 3.95 s | 11.74 s | 2.973 |
| asr.chunk | faster_whisper | 11.42 s | 19.37 s | 1.697 |
| asr.chunk | — | — | — | — |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 900.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,451,648,512 B (2.28 GiB) → — (not_measured) |
| swap used | 740,835,328 B (0.69 GiB) → — (not_measured) |
| memory pressure | some_avg10=0.07 → — (not_measured) |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | — (not_measured) |
| telemetry buffer peak | — (not_measured) |

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
  - context: `memory_pressure_end` (not_measured)
  - context: `process_rss_end` (not_measured)
  - context: `swap_used_end` (not_measured)
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `processing_wall_seconds` (not_measured)
  - run: `rtf` (not_measured)
  - run: `speedup` (not_measured)
  - run: `telemetry_buffer_peak_bytes` (not_measured)
  - run: `telemetry_overhead_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: language_detection 597.60 s (—); asr_primary 355.03 s (—); vad 31.56 s (—).
- Reprocessing ratio: — (not_measured).
- Cold loads: vad.model 2.98 s.
- Queue wait: 21.83 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: rtf unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: cold_model_init_share unavailable (not_measured) — rule `cold_model_init`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (not_measured) — rule `swap_growth`.

Checked, did not fire: `asr_device_configured`.

---

## Diagnostics — recording bc460637-23b9-4d4b-9968-dfd494cb5ac9

Run `e3290649-c4f0-4614-94b6-43223f04c2fd` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | bc460637-23b9-4d4b-9968-dfd494cb5ac9 |
| processing_run_id | e3290649-c4f0-4614-94b6-43223f04c2fd |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 537.85 s |
| rtf | 4.482 |
| speedup | 0.223 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.67 s | 0.1 % | -0.69 s |
| capture_input | asr.submit.probe | 1 | ok | 0.32 s | 0.1 % | -0.50 s |
| other | worker_job | 1 | ok | 241.48 s | — | +280.52 s |
| queue | · asr.queue_wait | 1 | ok | 280.50 s | 52.2 % | +0.02 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.28 s | 0.1 % | +280.52 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +280.80 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +280.80 s |
| vad | · vad.speech_runs | 1 | ok | 3.34 s | 0.6 % | +280.80 s |
| language_detection | · lid.run | 1 | ok | 9.62 s | 1.8 % | +284.14 s |
| language_detection | · lid.run | 1 | ok | 9.44 s | 1.8 % | +293.77 s |
| language_detection | · lid.run | 1 | ok | 9.77 s | 1.8 % | +303.22 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 1.8 % | +312.99 s |
| language_detection | · lid.run | 1 | ok | 9.52 s | 1.8 % | +322.70 s |
| language_detection | · lid.run | 1 | ok | 9.57 s | 1.8 % | +332.22 s |
| language_detection | · lid.run | 1 | ok | 9.69 s | 1.8 % | +341.80 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 153.49 s | 28.5 % | +351.48 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.25 s | 3.8 % | +351.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.61 s | 2.5 % | +371.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.74 s | 3.3 % | +385.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 36.99 s | 6.9 % | +403.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.58 s | 5.1 % | +440.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.33 s | 4.3 % | +467.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.95 s | 2.6 % | +491.03 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +504.98 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +504.98 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +504.99 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +504.99 s |
| diarization_infer | · diarization.infer | 1 | ok | 16.91 s | 3.1 % | +504.99 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +521.90 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +521.91 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +521.92 s |
| other | worker_job | 1 | skipped | 0.01 s | — | +522.03 s |
| queue | · asr.queue_wait | 1 | ok | 522.01 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +522.03 s |
| queue | · asr.queue_wait | 1 | ok | 522.02 s | — | +0.02 s |
| llm_call | llm.provider_probe | 1 | ok | 2.02 s | 0.4 % | +529.32 s |
| other | notes.generate | 1 | ok | 6.51 s | — | +531.34 s |
| llm_call | · llm.note_write | 1 | ok | 6.39 s | 1.2 % | +531.41 s |

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
| lid.run | 23.07 s | 9.62 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 9.44 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 9.77 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 9.71 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 9.52 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 9.57 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 9.69 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 20.25 s | 0.878 |
| asr.chunk | faster_whisper | 5.08 s | 13.61 s | 2.677 |
| asr.chunk | faster_whisper | 14.36 s | 17.74 s | 1.235 |
| asr.chunk | faster_whisper | 29.98 s | 36.99 s | 1.234 |
| asr.chunk | faster_whisper | 19.68 s | 27.58 s | 1.402 |
| asr.chunk | faster_whisper | 18.81 s | 23.33 s | 1.240 |
| asr.chunk | faster_whisper | 4.73 s | 13.95 s | 2.946 |

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
| infer | ok | 16.91 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 2.02 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.39 s | 1,085 | 0 | 0 | 290 | — (not_supported) |
| **total** |  | 2 |  |  | 8.41 s | 1,097 | 0 | 0 | 296 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,134,242,816 B (2.92 GiB) → 3,059,970,048 B (2.85 GiB) |
| swap used | 681,644,032 B (0.63 GiB) → 681,644,032 B (0.63 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.42 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,558 B |

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

- Top critical-path stages: queue 280.50 s (52.2 %); asr_primary 153.50 s (28.5 %); language_detection 67.31 s (12.5 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 280.50 s.
- LLM latency share of wall: 1.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording 0b07da37-7237-4334-96a5-6ef79b1e077d

Run `ebf66ca8-aaf9-4360-8645-b5452cb3dea9` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 0b07da37-7237-4334-96a5-6ef79b1e077d |
| processing_run_id | ebf66ca8-aaf9-4360-8645-b5452cb3dea9 |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 303.82 s |
| rtf | 2.532 |
| speedup | 0.395 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.42 s | 0.1 % | -0.45 s |
| capture_input | asr.submit.probe | 1 | ok | 0.17 s | 0.1 % | -0.36 s |
| other | worker_job | 1 | ok | 250.20 s | — | +33.64 s |
| queue | · asr.queue_wait | 1 | ok | 33.62 s | 11.1 % | +0.02 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.95 s | 0.3 % | +33.66 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +34.61 s |
| model_init | · vad.model | 1 | ok | 3.73 s | 1.2 % | +34.61 s |
| vad | · vad.speech_runs | 1 | ok | 7.24 s | 2.4 % | +38.34 s |
| language_detection | · lid.run | 1 | ok | 12.35 s | 4.1 % | +45.59 s |
| language_detection | · lid.run | 1 | ok | 10.07 s | 3.3 % | +57.95 s |
| language_detection | · lid.run | 1 | ok | 10.66 s | 3.5 % | +68.03 s |
| language_detection | · lid.run | 1 | ok | 10.74 s | 3.5 % | +78.70 s |
| language_detection | · lid.run | 1 | ok | 11.63 s | 3.8 % | +89.45 s |
| language_detection | · lid.run | 1 | ok | 11.71 s | 3.9 % | +101.09 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 3.0 % | +112.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 142.68 s | 47.0 % | +122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.75 s | 6.8 % | +122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.96 s | 4.3 % | +142.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.69 s | 5.8 % | +155.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 35.66 s | 11.7 % | +173.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.71 s | 7.8 % | +209.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.19 s | 6.0 % | +232.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.66 s | 4.5 % | +251.03 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +264.71 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +264.74 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +264.75 s |
| diarization_load | · diarization.load | 1 | ok | 3.49 s | 1.2 % | +264.75 s |
| diarization_infer | · diarization.infer | 1 | ok | 15.46 s | 5.1 % | +268.24 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +283.71 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +283.72 s |
| persist | · asr.persist | 1 | ok | 0.11 s | 0.0 % | +283.72 s |
| llm_call | llm.provider_probe | 1 | ok | 1.53 s | 0.5 % | +297.32 s |
| other | notes.generate | 1 | ok | 4.96 s | — | +298.86 s |
| llm_call | · llm.note_write | 1 | ok | 4.72 s | 1.6 % | +299.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +590.64 s |
| queue | · asr.queue_wait | 1 | ok | 590.62 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +590.66 s |
| queue | · asr.queue_wait | 1 | ok | 590.64 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +590.67 s |
| queue | · asr.queue_wait | 1 | ok | 590.65 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +590.68 s |
| queue | · asr.queue_wait | 1 | ok | 590.66 s | — | +0.02 s |

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
| lid.run | 23.07 s | 12.35 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 10.07 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.66 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 10.74 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 11.63 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 11.71 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 9.22 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 20.75 s | 0.900 |
| asr.chunk | faster_whisper | 5.08 s | 12.96 s | 2.549 |
| asr.chunk | faster_whisper | 14.36 s | 17.69 s | 1.232 |
| asr.chunk | faster_whisper | 29.98 s | 35.66 s | 1.189 |
| asr.chunk | faster_whisper | 19.68 s | 23.71 s | 1.205 |
| asr.chunk | faster_whisper | 18.81 s | 18.19 s | 0.967 |
| asr.chunk | faster_whisper | 4.73 s | 13.66 s | 2.885 |

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
| load | ok | 3.49 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 15.46 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.53 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.72 s | 1,085 | 0 | 0 | 297 | — (not_supported) |
| **total** |  | 2 |  |  | 6.25 s | 1,097 | 0 | 0 | 303 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,444,136,448 B (2.28 GiB) → 2,381,221,888 B (2.22 GiB) |
| swap used | 639,946,752 B (0.60 GiB) → 673,918,976 B (0.63 GiB) |
| memory pressure | some_avg10=0.43 → some_avg10=0.42 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.04 s |
| telemetry buffer peak | 1,143 B |

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

- Top critical-path stages: asr_primary 142.68 s (47.0 %); language_detection 76.39 s (25.1 %); queue 33.62 s (11.1 %).
- Reprocessing ratio: 0.964.
- Cold loads: vad.model 3.73 s; diarization.load 3.49 s.
- Queue wait: 33.62 s.
- LLM latency share of wall: 2.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording 64eed3a7-cf18-47d2-b76f-3da80049ff91

Run `9ac0280f-f122-43e6-b0ce-75cdcb976109` · reprocess · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 64eed3a7-cf18-47d2-b76f-3da80049ff91 |
| processing_run_id | 9ac0280f-f122-43e6-b0ce-75cdcb976109 |
| kind | reprocess (notes) |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 8.71 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | 10.01 s |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | ok | 0.89 s | 10.2 % | +0.97 s |
| other | notes.generate | 1 | ok | 6.84 s | — | +1.87 s |
| llm_call | · llm.note_write | 1 | ok | 6.10 s | 70.0 % | +2.30 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.89 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.10 s | 1,666 | 0 | 0 | 288 | — (not_supported) |
| **total** |  | 2 |  |  | 6.99 s | 1,678 | 0 | 0 | 294 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 2 |
| other model activity | none |
| telemetry overhead | 0.41 s |
| telemetry buffer peak | 273 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
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
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 6.99 s (80.2 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 80.2 %.
- UI delay (time_to_notes − processing_wall): 1.30 s.

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.

---

## Diagnostics — recording ecc56624-64b5-4173-8550-b33d1fcce977

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

---

## Diagnostics — recording edf28aaa-0e0b-4799-b6c4-63caeed852d8

Run `0d3ce71b-a2db-4e7b-ab03-18fe64c8de08` · reprocess · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | edf28aaa-0e0b-4799-b6c4-63caeed852d8 |
| processing_run_id | 0d3ce71b-a2db-4e7b-ab03-18fe64c8de08 |
| kind | reprocess (notes) |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 5.95 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | 6.44 s |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | ok | 1.05 s | 17.6 % | +1.12 s |
| other | notes.generate | 1 | ok | 3.78 s | — | +2.16 s |
| llm_call | · llm.note_write | 1 | ok | 3.45 s | 58.0 % | +2.42 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.05 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 3.45 s | 1,654 | 0 | 0 | 155 | — (not_supported) |
| **total** |  | 2 |  |  | 4.49 s | 1,666 | 0 | 0 | 161 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.15 s |
| telemetry buffer peak | 273 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
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
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 4.49 s (75.6 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 75.6 %.
- UI delay (time_to_notes − processing_wall): 0.49 s.

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.

---

## Diagnostics — recording 13697ab7-0edd-40fb-b605-018d2cdb03c8

Run `6c1b947a-68bf-4ffc-8604-9acf986984bd` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 13697ab7-0edd-40fb-b605-018d2cdb03c8 |
| processing_run_id | 6c1b947a-68bf-4ffc-8604-9acf986984bd |
| kind | initial |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 3 |
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
| processing_wall_seconds | 1990.62 s |
| rtf | 14.038 |
| speedup | 0.071 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.63 s | 0.0 % | -0.66 s |
| capture_input | asr.submit.probe | 1 | ok | 0.28 s | 0.0 % | -0.43 s |
| other | worker_job | 1 | cancelled | 157.51 s | — | +0.09 s |
| queue | · asr.queue_wait | 1 | ok | 0.07 s | 0.0 % | +0.03 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.78 s | 0.0 % | +0.13 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.91 s |
| model_init | · vad.model | 1 | ok | 3.09 s | 0.2 % | +0.91 s |
| vad | · vad.speech_runs | 1 | ok | 6.79 s | 0.3 % | +4.00 s |
| language_detection | · lid.run | 1 | ok | 12.72 s | 0.6 % | +10.80 s |
| language_detection | · lid.run | 1 | ok | 9.86 s | 0.5 % | +23.54 s |
| language_detection | · lid.run | 1 | ok | 10.15 s | 0.5 % | +33.40 s |
| language_detection | · lid.run | 1 | ok | 11.01 s | 0.6 % | +43.57 s |
| language_detection | · lid.run | 1 | ok | 11.85 s | 0.6 % | +54.59 s |
| language_detection | · lid.run | 1 | ok | 11.01 s | 0.6 % | +66.45 s |
| language_detection | · lid.run | 1 | ok | 11.66 s | 0.6 % | +77.47 s |
| language_detection | · lid.run | 1 | ok | 10.60 s | 0.5 % | +89.14 s |
| asr_primary | · asr.transcribe_runs | 1 | cancelled | 57.69 s | 2.9 % | +99.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 24.52 s | 1.2 % | +99.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.72 s | 0.7 % | +124.28 s |
| asr_primary | · · asr.chunk | 1 | cancelled | 19.40 s | 1.0 % | +138.02 s |
| other | worker_job | 2 | cancelled | 10.55 s | — | +1379.26 s |
| queue | · asr.queue_wait | 2 | ok | 1379.23 s | 69.3 % | +0.03 s |
| audio_prep | · asr.audio_prep | 2 | ok | 0.60 s | 0.0 % | +1379.28 s |
| model_init | · asr.model | 2 | ok | 0.00 s | 0.0 % | +1379.90 s |
| model_init | · vad.model | 2 | ok | 0.01 s | 0.0 % | +1379.90 s |
| vad | · vad.speech_runs | 2 | cancelled | 9.87 s | 0.5 % | +1379.91 s |
| other | worker_job | 3 | ok | 306.75 s | — | +1683.86 s |
| queue | · asr.queue_wait | 3 | ok | 1683.84 s | 84.6 % | +0.03 s |
| audio_prep | · asr.audio_prep | 3 | ok | 0.35 s | 0.0 % | +1683.87 s |
| model_init | · asr.model | 3 | ok | 0.00 s | 0.0 % | +1684.22 s |
| model_init | · vad.model | 3 | ok | 0.00 s | 0.0 % | +1684.23 s |
| vad | · vad.speech_runs | 3 | ok | 4.30 s | 0.2 % | +1684.23 s |
| language_detection | · lid.run | 3 | ok | 10.94 s | 0.5 % | +1688.53 s |
| language_detection | · lid.run | 3 | ok | 10.02 s | 0.5 % | +1699.47 s |
| language_detection | · lid.run | 3 | ok | 10.89 s | 0.5 % | +1709.51 s |
| language_detection | · lid.run | 3 | ok | 9.13 s | 0.5 % | +1720.41 s |
| language_detection | · lid.run | 3 | ok | 10.72 s | 0.5 % | +1729.55 s |
| language_detection | · lid.run | 3 | ok | 10.93 s | 0.5 % | +1740.28 s |
| language_detection | · lid.run | 3 | ok | 9.58 s | 0.5 % | +1751.22 s |
| language_detection | · lid.run | 3 | ok | 9.37 s | 0.5 % | +1760.80 s |
| asr_primary | · asr.transcribe_runs | 3 | ok | 204.15 s | 10.3 % | +1770.18 s |
| asr_primary | · · asr.chunk | 3 | ok | 23.03 s | 1.2 % | +1770.18 s |
| asr_primary | · · asr.chunk | 3 | ok | 19.06 s | 1.0 % | +1793.23 s |
| asr_primary | · · asr.chunk | 3 | ok | 28.27 s | 1.4 % | +1812.31 s |
| asr_primary | · · asr.chunk | 3 | ok | 34.58 s | 1.7 % | +1840.60 s |
| asr_primary | · · asr.chunk | 3 | ok | 45.21 s | 2.3 % | +1875.19 s |
| asr_primary | · · asr.chunk | 3 | ok | 22.36 s | 1.1 % | +1920.42 s |
| asr_primary | · · asr.chunk | 3 | ok | 18.45 s | 0.9 % | +1942.79 s |
| asr_primary | · · asr.chunk | 3 | ok | 13.08 s | 0.7 % | +1961.24 s |
| postprocess_cleanup | · asr.guards | 3 | ok | 0.00 s | 0.0 % | +1974.33 s |
| postprocess_cleanup | · asr.prompt_echo | 3 | ok | 0.00 s | 0.0 % | +1974.34 s |
| postprocess_cleanup | · asr.noise_markers | 3 | ok | 0.00 s | 0.0 % | +1974.34 s |
| diarization_load | · diarization.load | 3 | ok | 0.00 s | 0.0 % | +1974.34 s |
| diarization_infer | · diarization.infer | 3 | ok | 16.19 s | 0.8 % | +1974.34 s |
| postprocess_attribute | · asr.speaker_attribution | 3 | ok | 0.01 s | 0.0 % | +1990.54 s |
| postprocess_align | · asr.align | 3 | skipped | 0.00 s | — | +1990.55 s |
| persist | · asr.persist | 3 | ok | 0.06 s | 0.0 % | +1990.55 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.64 s |
| queue | · asr.queue_wait | 1 | ok | 1990.61 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.65 s |
| queue | · asr.queue_wait | 1 | ok | 1990.62 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.66 s |
| queue | · asr.queue_wait | 1 | ok | 1990.63 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.67 s |
| queue | · asr.queue_wait | 1 | ok | 1990.64 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.67 s |
| queue | · asr.queue_wait | 1 | ok | 1990.65 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.68 s |
| queue | · asr.queue_wait | 1 | ok | 1990.65 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.68 s |
| queue | · asr.queue_wait | 1 | ok | 1990.66 s | — | +0.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1990.69 s |
| queue | · asr.queue_wait | 1 | ok | 1990.66 s | — | +0.03 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 136.94 s | 8 | 4.71 s | 19.26 s | 28.70 s |
| vad.speech_runs | — | — | — | — | — |
| vad.speech_runs | 136.94 s | 8 | 4.71 s | 19.26 s | 28.70 s |

### Language checks

Language checks: 16.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 12.72 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 9.86 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.15 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 22.49 s | 11.01 s | de | de 0.997, en 0.002, es 0.000 |
| lid.run | 28.70 s | 11.85 s | en | en 0.985, cy 0.008, zh 0.001 |
| lid.run | 19.71 s | 11.01 s | en | en 0.996, cy 0.002, zh 0.001 |
| lid.run | 18.81 s | 11.66 s | en | en 0.970, cy 0.018, nn 0.003 |
| lid.run | 4.71 s | 10.60 s | en | en 0.942, nn 0.015, la 0.012 |
| lid.run | 23.07 s | 10.94 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 10.02 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.89 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 22.49 s | 9.13 s | de | de 0.997, en 0.002, es 0.000 |
| lid.run | 28.70 s | 10.72 s | en | en 0.985, cy 0.008, zh 0.001 |
| lid.run | 19.71 s | 10.93 s | en | en 0.996, cy 0.002, zh 0.001 |
| lid.run | 18.81 s | 9.58 s | en | en 0.970, cy 0.018, nn 0.003 |
| lid.run | 4.71 s | 9.37 s | en | en 0.942, nn 0.015, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 24.52 s | 1.063 |
| asr.chunk | faster_whisper | 5.08 s | 13.72 s | 2.699 |
| asr.chunk | — | — | 19.40 s | — |
| asr.chunk | faster_whisper | 23.07 s | 23.03 s | 0.999 |
| asr.chunk | faster_whisper | 5.08 s | 19.06 s | 3.748 |
| asr.chunk | faster_whisper | 14.36 s | 28.27 s | 1.968 |
| asr.chunk | faster_whisper | 22.49 s | 34.58 s | 1.537 |
| asr.chunk | faster_whisper | 28.70 s | 45.21 s | 1.575 |
| asr.chunk | faster_whisper | 19.71 s | 22.36 s | 1.135 |
| asr.chunk | faster_whisper | 18.81 s | 18.45 s | 0.981 |
| asr.chunk | faster_whisper | 4.71 s | 13.08 s | 2.777 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 16.19 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 6.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,443,812,864 B (2.28 GiB) → 3,134,091,264 B (2.92 GiB) |
| swap used | 1,235,996,672 B (1.15 GiB) → 681,644,032 B (0.63 GiB) |
| memory pressure | some_avg10=0.13 → some_avg10=0.06 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.22 s |
| telemetry buffer peak | 1,571 B |

### Missing measurements

- **asr_primary**
  - asr.chunk: `audio_processed_seconds` (not_measured)
  - asr.chunk: `backend` (not_measured)
  - asr.chunk: `beam_size` (not_measured)
  - asr.chunk: `chunk_count` (not_measured)
  - asr.chunk: `chunk_seconds` (not_measured)
  - asr.chunk: `compute_type` (not_measured)
  - asr.chunk: `device` (not_measured)
  - asr.chunk: `model` (not_measured)
  - asr.chunk: `segment_count` (not_measured)
  - asr.chunk: `wall_seconds` (not_measured)
  - asr.chunk: `word_count` (not_measured)
  - asr.transcribe_runs: `audio_processed_seconds` (not_measured)
  - asr.transcribe_runs: `chunk_count` (not_measured)
  - asr.transcribe_runs: `chunk_seconds` (not_measured)
  - asr.transcribe_runs: `segment_count` (not_measured)
  - asr.transcribe_runs: `wall_seconds` (not_measured)
  - asr.transcribe_runs: `word_count` (not_measured)
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
- **vad**
  - vad.speech_runs: `backend` (not_measured)
  - vad.speech_runs: `duration_seconds` (not_measured)
  - vad.speech_runs: `run_count` (not_measured)
  - vad.speech_runs: `run_lengths_seconds` (not_measured)
  - vad.speech_runs: `speech_seconds` (not_measured)
  - vad.speech_runs: `threshold` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: queue 1683.84 s (84.6 %); asr_primary 261.85 s (13.2 %); language_detection 170.45 s (8.6 %).
- Reprocessing ratio: 0.966.
- Cold loads: vad.model 3.09 s.
- Queue wait: 3063.13 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording ec4f4e12-2d81-4207-b67b-34899cf28920

Run `351eccc5-b48c-4a6c-998c-0b996fce9c14` · initial · cancelled

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ec4f4e12-2d81-4207-b67b-34899cf28920 |
| processing_run_id | 351eccc5-b48c-4a6c-998c-0b996fce9c14 |
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
| audio duration | 900.00 s |
| processing_wall_seconds | 91.62 s |
| rtf | 0.102 |
| speedup | 9.823 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.56 s | 0.6 % | -0.57 s |
| capture_input | asr.submit.probe | 1 | ok | 0.15 s | 0.2 % | -0.39 s |
| other | worker_job | 1 | cancelled | 91.60 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.79 s | 0.9 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.83 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.83 s |
| vad | · vad.speech_runs | 1 | ok | 36.51 s | 39.8 % | +0.83 s |
| language_detection | · lid.run | 1 | ok | 11.98 s | 13.1 % | +37.37 s |
| language_detection | · lid.run | 1 | ok | 11.38 s | 12.4 % | +49.36 s |
| language_detection | · lid.run | 1 | ok | 10.13 s | 11.1 % | +60.75 s |
| language_detection | · lid.run | 1 | ok | 10.65 s | 11.6 % | +70.89 s |
| language_detection | · lid.run | 1 | ok | 10.03 s | 11.0 % | +81.55 s |
| other | worker_job | 1 | cancelled | 0.00 s | — | +91.64 s |
| queue | · asr.queue_wait | 1 | ok | 91.64 s | — | +0.01 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 866.14 s | 61 | 1.12 s | 11.42 s | 30.00 s |

### Language checks

Language checks: 5.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 10.68 s | 11.98 s | en | en 0.982, cy 0.008, la 0.003 |
| lid.run | 14.91 s | 11.38 s | en | en 0.995, cy 0.003, la 0.000 |
| lid.run | 8.44 s | 10.13 s | en | en 0.996, cy 0.002, la 0.001 |
| lid.run | 2.04 s | 10.65 s | en | en 0.975, cy 0.007, nn 0.002 |
| lid.run | 4.89 s | 10.03 s | en | en 0.986, cy 0.009, la 0.001 |

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 900.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,389,872,640 B (2.23 GiB) → 3,113,046,016 B (2.90 GiB) |
| swap used | 1,238,114,304 B (1.15 GiB) → 1,237,303,296 B (1.15 GiB) |
| memory pressure | some_avg10=0.18 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.10 s |
| telemetry buffer peak | 1,114 B |

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

- Top critical-path stages: language_detection 54.19 s (59.1 %); vad 36.51 s (39.8 %); audio_prep 0.79 s (0.9 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `cold_model_init`, `swap_growth`.

---

## Diagnostics — recording ae8bafef-7b45-4e09-82a7-47a07e8da12d

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

---

## Diagnostics — recording 4a390264-ce5a-4ceb-ab69-4d4aafb659f1

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

---

## Diagnostics — recording 7a06a6e4-9a36-427c-8f34-5ec0e7d92b95

Run `17846383-6dcd-4ba8-90aa-51cdcb3e844e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7a06a6e4-9a36-427c-8f34-5ec0e7d92b95 |
| processing_run_id | 17846383-6dcd-4ba8-90aa-51cdcb3e844e |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 324.24 s |
| rtf | 2.702 |
| speedup | 0.370 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.32 s | 0.1 % | -0.33 s |
| capture_input | asr.submit.probe | 1 | ok | 0.14 s | 0.0 % | -0.26 s |
| other | worker_job | 1 | ok | 282.32 s | — | +0.04 s |
| queue | · asr.queue_wait | 1 | ok | 0.03 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.25 s | 0.1 % | +0.06 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.31 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.31 s |
| vad | · vad.speech_runs | 1 | ok | 4.83 s | 1.5 % | +0.32 s |
| language_detection | · lid.run | 1 | ok | 11.34 s | 3.5 % | +5.15 s |
| language_detection | · lid.run | 1 | ok | 11.77 s | 3.6 % | +16.49 s |
| language_detection | · lid.run | 1 | ok | 10.62 s | 3.3 % | +28.28 s |
| language_detection | · lid.run | 1 | ok | 9.99 s | 3.1 % | +38.91 s |
| language_detection | · lid.run | 1 | ok | 10.45 s | 3.2 % | +48.90 s |
| language_detection | · lid.run | 1 | ok | 10.60 s | 3.3 % | +59.37 s |
| language_detection | · lid.run | 1 | ok | 10.58 s | 3.3 % | +69.97 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 185.24 s | 57.1 % | +80.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.91 s | 8.6 % | +80.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.86 s | 5.5 % | +108.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.33 s | 6.9 % | +126.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 49.09 s | 15.1 % | +148.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.56 s | 9.1 % | +197.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.61 s | 7.0 % | +227.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.79 s | 4.9 % | +250.00 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +265.80 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +265.80 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +265.81 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +265.81 s |
| diarization_infer | · diarization.infer | 1 | ok | 16.46 s | 5.1 % | +265.81 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +282.27 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +282.28 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +282.28 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.39 s |
| queue | · asr.queue_wait | 1 | ok | 282.37 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.39 s |
| queue | · asr.queue_wait | 1 | ok | 282.38 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.40 s |
| queue | · asr.queue_wait | 1 | ok | 282.39 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.40 s |
| queue | · asr.queue_wait | 1 | ok | 282.39 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 8.22 s | 2.5 % | +304.58 s |
| other | notes.generate | 1 | ok | 11.44 s | — | +312.80 s |
| llm_call | · llm.note_write | 1 | error | 0.00 s | 0.0 % | +313.20 s |
| llm_call | · llm.note_write | 1 | ok | 9.94 s | 3.1 % | +314.21 s |

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
| lid.run | 23.07 s | 11.34 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 11.77 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.62 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 9.99 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 10.45 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 10.60 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 10.58 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 27.91 s | 1.210 |
| asr.chunk | faster_whisper | 5.08 s | 17.86 s | 3.513 |
| asr.chunk | faster_whisper | 14.36 s | 22.33 s | 1.554 |
| asr.chunk | faster_whisper | 29.98 s | 49.09 s | 1.638 |
| asr.chunk | faster_whisper | 19.68 s | 29.56 s | 1.502 |
| asr.chunk | faster_whisper | 18.81 s | 22.61 s | 1.202 |
| asr.chunk | faster_whisper | 4.73 s | 15.79 s | 3.336 |

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
| infer | ok | 16.46 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.22 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | error | — (not_applicable) | 0.00 s | 1,205* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 2 | ok | — (not_applicable) | 9.94 s | 1,085 | 0 | 0 | 335 | — (not_supported) |
| **total** |  | 3 |  |  | 18.15 s | 2,302 | 0 | 0 | 341 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again; estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,371,727,360 B (2.21 GiB) → 3,219,263,488 B (3.00 GiB) |
| swap used | 1,262,321,664 B (1.18 GiB) → 1,260,498,944 B (1.17 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.12 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,561 B |

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
  - llm.note_write: `finish_reason` (unavailable)
  - llm.note_write: `http_status` (unavailable)
  - llm.provider_probe: `error_subtype` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - note_write (attempt 1): `cached_input_tokens` (unavailable)
  - note_write (attempt 1): `completion_chars` (unavailable)
  - note_write (attempt 1): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 1): `model_load_seconds` (not_applicable)
  - note_write (attempt 1): `output_tokens` (unavailable)
  - note_write (attempt 1): `reasoning_tokens` (unavailable)
  - note_write (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - note_write (attempt 2): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 2): `model_load_seconds` (unavailable)
  - note_write (attempt 2): `time_to_first_token_seconds` (not_applicable)
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

- Top critical-path stages: asr_primary 185.25 s (57.1 %); language_detection 75.35 s (23.2 %); llm_call 18.16 s (5.6 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 0.03 s.
- LLM latency share of wall: 5.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording edf28aaa-0e0b-4799-b6c4-63caeed852d8

Run `a081fa3a-e416-4b34-807e-9cb106b81324` · reprocess · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | edf28aaa-0e0b-4799-b6c4-63caeed852d8 |
| processing_run_id | a081fa3a-e416-4b34-807e-9cb106b81324 |
| kind | reprocess (notes) |
| trigger | user |
| status | failed |
| error category | llm |
| attempt | 3 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | dev_mac | notes-chat | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 59.39 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | error | 0.02 s | 0.0 % | +1.04 s |
| llm_call | llm.provider_probe | 1 | error | 0.24 s | 0.4 % | +2.10 s |
| llm_call | llm.provider_probe | 1 | error | 0.06 s | 0.1 % | +4.37 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +22.94 s |
| llm_call | llm.provider_probe | 2 | error | 0.04 s | 0.1 % | +23.96 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +26.00 s |
| llm_call | llm.provider_probe | 3 | error | 0.03 s | 0.0 % | +56.33 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +57.36 s |
| llm_call | llm.provider_probe | 3 | error | 0.02 s | 0.0 % | +59.38 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.02 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.25 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.06 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.04 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.03 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| **total** |  | 9 |  |  | 0.45 s | 72 | — | — | — |  |

Token accounting: estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 2 |
| other model activity | none |
| telemetry overhead | 0.30 s |
| telemetry buffer peak | 264 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
- **llm_call**
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 2): `completion_chars` (unavailable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `output_tokens` (unavailable)
  - provider_probe (attempt 2): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 3): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 3): `completion_chars` (unavailable)
  - provider_probe (attempt 3): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 3): `model_load_seconds` (unavailable)
  - provider_probe (attempt 3): `output_tokens` (unavailable)
  - provider_probe (attempt 3): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 3): `time_to_first_token_seconds` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 0.45 s (0.8 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 0.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.

---

## Diagnostics — recording 64eed3a7-cf18-47d2-b76f-3da80049ff91

Run `68645c41-b3a4-4d41-b517-411e2aa5ff2d` · reprocess · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 64eed3a7-cf18-47d2-b76f-3da80049ff91 |
| processing_run_id | 68645c41-b3a4-4d41-b517-411e2aa5ff2d |
| kind | reprocess (notes) |
| trigger | user |
| status | failed |
| error category | llm |
| attempt | 3 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | dev_mac | notes-chat | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 55.50 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | error | 0.03 s | 0.1 % | +0.69 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +1.72 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +3.74 s |
| llm_call | llm.provider_probe | 2 | error | 0.05 s | 0.1 % | +19.10 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +20.16 s |
| llm_call | llm.provider_probe | 2 | error | 0.08 s | 0.1 % | +22.20 s |
| llm_call | llm.provider_probe | 3 | error | 0.04 s | 0.1 % | +52.41 s |
| llm_call | llm.provider_probe | 3 | error | 0.02 s | 0.0 % | +53.46 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +55.48 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.03 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.04 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.08 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.04 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.02 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| **total** |  | 9 |  |  | 0.27 s | 72 | — | — | — |  |

Token accounting: estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.27 s |
| telemetry buffer peak | 264 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
- **llm_call**
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 2): `completion_chars` (unavailable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `output_tokens` (unavailable)
  - provider_probe (attempt 2): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 3): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 3): `completion_chars` (unavailable)
  - provider_probe (attempt 3): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 3): `model_load_seconds` (unavailable)
  - provider_probe (attempt 3): `output_tokens` (unavailable)
  - provider_probe (attempt 3): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 3): `time_to_first_token_seconds` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 0.28 s (0.5 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 0.5 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.

---

## Diagnostics — recording 30f4302c-4dc2-4de3-a476-e4466b70c963

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
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 120.00 s |
| processing_wall_seconds | 4918.44 s |
| rtf | 40.987 |
| speedup | 0.024 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | 4914.46 s |
| time_to_speaker_labels_seconds | 4914.46 s |
| time_to_notes_seconds | 4965.24 s |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.24 s | 0.0 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.12 s | 0.0 % | -0.21 s |
| other | worker_job | 1 | ok | 389.85 s | — | +288.65 s |
| queue | · asr.queue_wait | 1 | ok | 288.64 s | 5.9 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.27 s | 0.0 % | +288.65 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +288.92 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +288.92 s |
| vad | · vad.speech_runs | 1 | ok | 4.89 s | 0.1 % | +288.92 s |
| language_detection | · lid.run | 1 | ok | 11.52 s | 0.2 % | +293.82 s |
| language_detection | · lid.run | 1 | ok | 9.42 s | 0.2 % | +305.35 s |
| language_detection | · lid.run | 1 | ok | 12.18 s | 0.2 % | +314.77 s |
| language_detection | · lid.run | 1 | ok | 10.39 s | 0.2 % | +326.96 s |
| language_detection | · lid.run | 1 | ok | 11.55 s | 0.2 % | +337.36 s |
| language_detection | · lid.run | 1 | ok | 10.29 s | 0.2 % | +348.92 s |
| language_detection | · lid.run | 1 | ok | 10.48 s | 0.2 % | +359.22 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 291.56 s | 5.9 % | +369.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 46.58 s | 0.9 % | +369.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 38.38 s | 0.8 % | +416.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.58 s | 0.8 % | +454.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 76.21 s | 1.5 % | +496.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 40.72 s | 0.8 % | +572.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 28.99 s | 0.6 % | +613.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.96 s | 0.4 % | +642.29 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +661.26 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +661.27 s |
| diarization_infer | · diarization.infer | 1 | ok | 17.12 s | 0.3 % | +661.27 s |
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
| llm_call | llm.provider_probe | 1 | ok | 0.72 s | 0.0 % | +4912.57 s |
| other | notes.generate | 1 | ok | 5.15 s | — | +4913.30 s |
| llm_call | · llm.note_write | 1 | ok | 5.00 s | 0.1 % | +4913.37 s |

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

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.72 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.00 s | 1,666 | 0 | 0 | 300 | — (not_supported) |
| **total** |  | 2 |  |  | 5.72 s | 1,678 | 0 | 0 | 306 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,989,780,992 B (2.78 GiB) → 2,371,092,480 B (2.21 GiB) |
| swap used | 1,277,227,008 B (1.19 GiB) → 1,268,621,312 B (1.18 GiB) |
| memory pressure | some_avg10=0.35 → some_avg10=0.54 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.04 s |
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
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 291.56 s (5.9 %); queue 288.64 s (5.9 %); language_detection 75.82 s (1.5 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 288.64 s.
- LLM latency share of wall: 0.1 %.
- UI delay (time_to_notes − processing_wall): 46.79 s.

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording 64eed3a7-cf18-47d2-b76f-3da80049ff91

Run `e608a97d-fede-4b4d-8fb5-1384f247a82b` · initial · partial

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 64eed3a7-cf18-47d2-b76f-3da80049ff91 |
| processing_run_id | e608a97d-fede-4b4d-8fb5-1384f247a82b |
| kind | initial |
| trigger | user |
| status | partial |
| error category | llm |
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
| llm | dev_mac | notes-chat | — | — | — | — | — |
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 120.00 s |
| processing_wall_seconds | 521.97 s |
| rtf | 4.350 |
| speedup | 0.230 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | 532.38 s |
| time_to_speaker_labels_seconds | 532.38 s |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.36 s | 0.1 % | -0.37 s |
| capture_input | asr.submit.probe | 1 | ok | 0.19 s | 0.0 % | -0.31 s |
| other | worker_job | 1 | ok | 289.12 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.25 s | 0.0 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.29 s |
| vad | · vad.speech_runs | 1 | ok | 5.86 s | 1.1 % | +0.30 s |
| language_detection | · lid.run | 1 | ok | 12.45 s | 2.4 % | +6.17 s |
| language_detection | · lid.run | 1 | ok | 16.03 s | 3.1 % | +18.63 s |
| language_detection | · lid.run | 1 | ok | 12.58 s | 2.4 % | +34.69 s |
| language_detection | · lid.run | 1 | ok | 11.96 s | 2.3 % | +47.34 s |
| language_detection | · lid.run | 1 | ok | 11.57 s | 2.2 % | +59.31 s |
| language_detection | · lid.run | 1 | ok | 11.91 s | 2.3 % | +70.89 s |
| language_detection | · lid.run | 1 | ok | 11.23 s | 2.2 % | +82.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 176.31 s | 33.8 % | +94.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 32.48 s | 6.2 % | +94.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.75 s | 2.8 % | +126.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.06 s | 3.8 % | +141.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.48 s | 7.9 % | +161.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 30.18 s | 5.8 % | +202.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.83 s | 4.2 % | +233.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.43 s | 3.0 % | +254.92 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +270.36 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +270.39 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +270.39 s |
| diarization_load | · diarization.load | 1 | ok | 3.48 s | 0.7 % | +270.39 s |
| diarization_infer | · diarization.infer | 1 | ok | 15.14 s | 2.9 % | +273.88 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +289.02 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +289.03 s |
| persist | · asr.persist | 1 | ok | 0.11 s | 0.0 % | +289.03 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.17 s |
| queue | · asr.queue_wait | 1 | ok | 289.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.18 s |
| queue | · asr.queue_wait | 1 | ok | 289.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.19 s |
| queue | · asr.queue_wait | 1 | ok | 289.18 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +289.19 s |
| queue | · asr.queue_wait | 1 | ok | 289.19 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +466.48 s |
| llm_call | llm.provider_probe | 1 | error | 0.03 s | 0.0 % | +467.50 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +469.53 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +485.08 s |
| llm_call | llm.provider_probe | 2 | error | 0.05 s | 0.0 % | +486.10 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +488.16 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +518.91 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +519.94 s |
| llm_call | llm.provider_probe | 3 | error | 0.02 s | 0.0 % | +521.95 s |

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
| lid.run | 23.07 s | 12.45 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 16.03 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 12.58 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 11.96 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 11.57 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 11.91 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 11.23 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 32.48 s | 1.408 |
| asr.chunk | faster_whisper | 5.08 s | 14.75 s | 2.901 |
| asr.chunk | faster_whisper | 14.36 s | 20.06 s | 1.396 |
| asr.chunk | faster_whisper | 29.98 s | 41.48 s | 1.384 |
| asr.chunk | faster_whisper | 19.68 s | 30.18 s | 1.534 |
| asr.chunk | faster_whisper | 18.81 s | 21.83 s | 1.160 |
| asr.chunk | faster_whisper | 4.73 s | 15.43 s | 3.260 |

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
| load | ok | 3.48 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 15.14 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.03 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.05 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — (unavailable) | — (unavailable) | — (unavailable) | — (not_supported) |
| **total** |  | 9 |  |  | 0.16 s | 72 | — | — | — |  |

Token accounting: estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,601,766,912 B (2.42 GiB) → 2,989,711,360 B (2.78 GiB) |
| swap used | 1,286,168,576 B (1.20 GiB) → 1,277,231,104 B (1.19 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.35 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.23 s |
| telemetry buffer peak | 1,310 B |

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
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 2): `completion_chars` (unavailable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `output_tokens` (unavailable)
  - provider_probe (attempt 2): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 3): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 3): `completion_chars` (unavailable)
  - provider_probe (attempt 3): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 3): `model_load_seconds` (unavailable)
  - provider_probe (attempt 3): `output_tokens` (unavailable)
  - provider_probe (attempt 3): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 3): `time_to_first_token_seconds` (not_applicable)
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
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 176.31 s (33.8 %); language_detection 87.74 s (16.8 %); diarization_infer 15.14 s (2.9 %).
- Reprocessing ratio: 0.964.
- Cold loads: diarization.load 3.48 s.
- Queue wait: 0.02 s.
- LLM latency share of wall: 0.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.

---

## Diagnostics — recording eb2040bd-280c-409d-b10d-61f8c9a083b6

Run `52f7bff1-1575-4eef-84e7-fd230ec53f01` · initial · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | eb2040bd-280c-409d-b10d-61f8c9a083b6 |
| processing_run_id | 52f7bff1-1575-4eef-84e7-fd230ec53f01 |
| kind | initial |
| trigger | user |
| status | failed |
| error category | input |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 25.19 s |
| rtf | 0.210 |
| speedup | 4.764 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.53 s | 2.1 % | -0.54 s |
| capture_input | asr.submit.probe | 1 | ok | 0.34 s | 1.3 % | -0.49 s |
| other | worker_job | 1 | error | 4.18 s | — | +21.00 s |
| queue | · asr.queue_wait | 1 | ok | 21.00 s | 83.4 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.95 s | 3.8 % | +21.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +21.98 s |
| model_init | · vad.model | 1 | ok | 3.10 s | 12.3 % | +21.98 s |
| vad | · vad.speech_runs | 1 | ok | 0.09 s | 0.4 % | +25.08 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +25.18 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +25.18 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +25.18 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 0.00 s | 0 | — | — | — |

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 120.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,053,440 B (2.28 GiB) → 2,599,002,112 B (2.42 GiB) |
| swap used | 1,291,948,032 B (1.20 GiB) → 1,291,890,688 B (1.20 GiB) |
| memory pressure | some_avg10=0.21 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.08 s |
| telemetry buffer peak | 951 B |

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

- Top critical-path stages: queue 21.00 s (83.4 %); model_init 3.10 s (12.3 %); audio_prep 0.95 s (3.8 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: vad.model 3.10 s.
- Queue wait: 21.00 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Hypothesis: model loading takes 12.3 % of wall (cold model_init); keep models warm.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `swap_growth`.

---

## Diagnostics — recording 164eff6c-a061-4cfc-b15a-0ff98d853f52

Run `2b4846f9-138a-4fbe-92d4-c6567822f95e` · initial · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 164eff6c-a061-4cfc-b15a-0ff98d853f52 |
| processing_run_id | 2b4846f9-138a-4fbe-92d4-c6567822f95e |
| kind | initial |
| trigger | user |
| status | failed |
| error category | asr |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 3.56 s |
| rtf | 0.030 |
| speedup | 33.732 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 1.29 s | 36.2 % | -1.31 s |
| capture_input | asr.submit.probe | 1 | ok | 0.39 s | 11.0 % | -1.28 s |
| other | worker_job | 1 | error | 3.51 s | — | +0.05 s |
| queue | · asr.queue_wait | 1 | ok | 0.04 s | 1.1 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.71 s | 20.0 % | +0.06 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.78 s |
| model_init | · vad.model | 1 | ok | 2.57 s | 72.2 % | +0.78 s |
| vad | · vad.speech_runs | 1 | ok | 0.19 s | 5.5 % | +3.35 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +3.55 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +3.55 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +3.55 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 0.00 s | 0 | — | — | — |

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 120.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,444,632,064 B (2.28 GiB) → 2,594,185,216 B (2.42 GiB) |
| swap used | 1,298,341,888 B (1.21 GiB) → 1,298,087,936 B (1.21 GiB) |
| memory pressure | some_avg10=0.34 → some_avg10=0.23 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.15 s |
| telemetry buffer peak | 951 B |

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

- Top critical-path stages: model_init 2.57 s (72.2 %); upload 1.29 s (36.2 %); audio_prep 0.71 s (20.0 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: vad.model 2.57 s.
- Queue wait: 0.04 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Hypothesis: model loading takes 72.2 % of wall (cold model_init); keep models warm.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `swap_growth`.

---

## Diagnostics — recording 78f2823c-3ce8-41e4-9bea-dfcd83f3c646

Run `18e1c7b8-bd5b-4b24-a835-2964f7f72f92` · reprocess · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 78f2823c-3ce8-41e4-9bea-dfcd83f3c646 |
| processing_run_id | 18e1c7b8-bd5b-4b24-a835-2964f7f72f92 |
| kind | reprocess (notes) |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 3.69 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | ok | 0.63 s | 17.0 % | +0.58 s |
| other | notes.generate | 1 | ok | 2.48 s | — | +1.21 s |
| llm_call | · llm.note_write | 1 | ok | 2.15 s | 58.3 % | +1.46 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 2.15 s | 1,654 | 0 | 0 | 137 | — (not_supported) |
| **total** |  | 2 |  |  | 2.77 s | 1,666 | 0 | 0 | 143 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 273 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
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
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 2.78 s (75.2 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 75.2 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.

---

## Diagnostics — recording 78f2823c-3ce8-41e4-9bea-dfcd83f3c646

Run `83d1f157-04db-4fc2-99e2-241cc8e8c12f` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 78f2823c-3ce8-41e4-9bea-dfcd83f3c646 |
| processing_run_id | 83d1f157-04db-4fc2-99e2-241cc8e8c12f |
| kind | initial |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — (unavailable) |
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
| audio duration | 90.00 s |
| processing_wall_seconds | 212.82 s |
| rtf | 2.365 |
| speedup | 0.423 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | 7797.68 s |
| time_to_speaker_labels_seconds | 7797.68 s |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.82 s | 0.4 % | -0.83 s |
| capture_input | asr.submit.probe | 1 | ok | 0.39 s | 0.2 % | -0.66 s |
| other | worker_job | 1 | ok | 212.73 s | — | +0.09 s |
| queue | · asr.queue_wait | 1 | ok | 0.06 s | 0.0 % | +0.04 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.16 s | 0.5 % | +0.11 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +1.27 s |
| model_init | · vad.model | 1 | ok | 2.80 s | 1.3 % | +1.27 s |
| vad | · vad.speech_runs | 1 | ok | 4.50 s | 2.1 % | +4.07 s |
| language_detection | · lid.recording | 1 | ok | 10.99 s | 5.2 % | +8.57 s |
| language_detection | · lid.run | 1 | ok | 13.06 s | 6.1 % | +19.58 s |
| language_detection | · lid.run | 1 | ok | 11.78 s | 5.5 % | +32.66 s |
| language_detection | · lid.run | 1 | ok | 11.17 s | 5.2 % | +44.46 s |
| language_detection | · lid.run | 1 | ok | 11.54 s | 5.4 % | +55.63 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | 4.9 % | +67.18 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 119.14 s | 56.0 % | +77.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.37 s | 8.6 % | +77.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.18 s | 12.8 % | +95.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 26.35 s | 12.4 % | +123.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.73 s | 11.1 % | +149.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.45 s | 11.0 % | +173.19 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +196.65 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +196.68 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +196.68 s |
| diarization_load | · diarization.load | 1 | ok | 4.25 s | 2.0 % | +196.68 s |
| diarization_infer | · diarization.infer | 1 | ok | 11.77 s | 5.5 % | +200.93 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +212.70 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +212.71 s |
| persist | · asr.persist | 1 | ok | 0.09 s | 0.0 % | +212.71 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +212.84 s |
| queue | · asr.queue_wait | 1 | ok | 212.80 s | — | +0.04 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +212.85 s |
| queue | · asr.queue_wait | 1 | ok | 212.81 s | — | +0.04 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 86.08 s | 5 | 9.41 s | 19.20 s | 19.20 s |

### Language checks

Language checks: 6.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 86.08 s | 10.99 s | de | de 0.998, en 0.001, tr 0.000 |
| lid.run | 9.41 s | 13.06 s | de | de 0.995, en 0.002, it 0.000 |
| lid.run | 19.20 s | 11.78 s | de | de 0.998, en 0.001, it 0.000 |
| lid.run | 19.20 s | 11.17 s | de | de 0.998, en 0.001, ja 0.000 |
| lid.run | 19.20 s | 11.54 s | de | de 0.999, en 0.000, es 0.000 |
| lid.run | 19.09 s | 10.33 s | de | de 0.999, en 0.000, ja 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 9.41 s | 18.37 s | 1.953 |
| asr.chunk | faster_whisper | 19.20 s | 27.17 s | 1.416 |
| asr.chunk | faster_whisper | 19.20 s | 26.35 s | 1.373 |
| asr.chunk | faster_whisper | 19.20 s | 23.73 s | 1.236 |
| asr.chunk | faster_whisper | 19.09 s | 23.45 s | 1.229 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 86.08 s |
| audio duration | 90.00 s |
| reprocessing ratio | 0.956 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 4.25 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 11.77 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 1 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,442,072,064 B (2.27 GiB) → 3,049,246,720 B (2.84 GiB) |
| swap used | 712,880,128 B (0.66 GiB) → 709,349,376 B (0.66 GiB) |
| memory pressure | some_avg10=0.14 → some_avg10=1.06 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.30 s |
| telemetry buffer peak | 1,130 B |

### Missing measurements

- **audio_prep**
  - asr.audio_prep: `decrypt_seconds` (not_supported)
  - asr.audio_prep: `resample_seconds` (not_supported)
  - asr.audio_prep: `source_sample_rate_hz` (unavailable)
- **context**
  - context: `app_build` (unavailable)
  - context: `app_commit` (unavailable)
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
- **queue**
  - asr.queue_wait: `queue_depth_at_enqueue` (unavailable)
- **run**
  - run: `time_to_notes_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 119.14 s (56.0 %); language_detection 68.88 s (32.4 %); diarization_infer 11.77 s (5.5 %).
- Reprocessing ratio: 0.956.
- Cold loads: vad.model 2.80 s; diarization.load 4.25 s.
- Queue wait: 0.06 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
