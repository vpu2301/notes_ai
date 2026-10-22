# Diagnostics — recording 7967deba-52de-45d6-a0e2-1356966ffc9c

Run `f2e27fc8-efdc-4d1f-9ffe-ffcc13065477` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7967deba-52de-45d6-a0e2-1356966ffc9c |
| processing_run_id | f2e27fc8-efdc-4d1f-9ffe-ffcc13065477 |
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
| audio duration | 900.00 s |
| processing_wall_seconds | 2307.34 s |
| rtf | 2.564 |
| speedup | 0.390 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 1.09 s | 0.0 % | -1.10 s |
| capture_input | asr.submit.probe | 1 | ok | 0.24 s | 0.0 % | -0.57 s |
| other | worker_job | 1 | ok | 2259.64 s | — | +21.84 s |
| queue | · asr.queue_wait | 1 | ok | 21.83 s | 0.9 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.50 s | 0.1 % | +21.86 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +23.37 s |
| model_init | · vad.model | 1 | ok | 2.98 s | 0.1 % | +23.37 s |
| vad | · vad.speech_runs | 1 | ok | 31.55 s | 1.4 % | +26.35 s |
| language_detection | · lid.run | 1 | ok | 10.88 s | 0.5 % | +57.93 s |
| language_detection | · lid.run | 1 | ok | 9.77 s | 0.4 % | +68.81 s |
| language_detection | · lid.run | 1 | ok | 9.50 s | 0.4 % | +78.59 s |
| language_detection | · lid.run | 1 | ok | 9.66 s | 0.4 % | +88.09 s |
| language_detection | · lid.run | 1 | ok | 12.68 s | 0.5 % | +97.76 s |
| language_detection | · lid.run | 1 | ok | 11.33 s | 0.5 % | +110.46 s |
| language_detection | · lid.run | 1 | ok | 9.78 s | 0.4 % | +121.80 s |
| language_detection | · lid.run | 1 | ok | 11.68 s | 0.5 % | +131.58 s |
| language_detection | · lid.run | 1 | ok | 9.84 s | 0.4 % | +143.27 s |
| language_detection | · lid.run | 1 | ok | 9.70 s | 0.4 % | +153.12 s |
| language_detection | · lid.run | 1 | ok | 9.86 s | 0.4 % | +162.83 s |
| language_detection | · lid.run | 1 | ok | 9.81 s | 0.4 % | +172.70 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | 0.4 % | +182.52 s |
| language_detection | · lid.run | 1 | ok | 8.70 s | 0.4 % | +191.52 s |
| language_detection | · lid.run | 1 | ok | 14.83 s | 0.6 % | +200.22 s |
| language_detection | · lid.run | 1 | ok | 11.36 s | 0.5 % | +215.06 s |
| language_detection | · lid.run | 1 | ok | 9.93 s | 0.4 % | +226.42 s |
| language_detection | · lid.run | 1 | ok | 10.79 s | 0.5 % | +236.35 s |
| language_detection | · lid.run | 1 | ok | 9.49 s | 0.4 % | +247.15 s |
| language_detection | · lid.run | 1 | ok | 9.87 s | 0.4 % | +256.65 s |
| language_detection | · lid.run | 1 | ok | 12.43 s | 0.5 % | +266.53 s |
| language_detection | · lid.run | 1 | ok | 13.31 s | 0.6 % | +278.97 s |
| language_detection | · lid.run | 1 | ok | 19.38 s | 0.8 % | +292.31 s |
| language_detection | · lid.run | 1 | ok | 12.43 s | 0.5 % | +311.84 s |
| language_detection | · lid.run | 1 | ok | 11.48 s | 0.5 % | +324.27 s |
| language_detection | · lid.run | 1 | ok | 9.94 s | 0.4 % | +335.76 s |
| language_detection | · lid.run | 1 | ok | 9.45 s | 0.4 % | +345.71 s |
| language_detection | · lid.run | 1 | ok | 10.60 s | 0.5 % | +355.17 s |
| language_detection | · lid.run | 1 | ok | 13.88 s | 0.6 % | +365.78 s |
| language_detection | · lid.run | 1 | ok | 11.82 s | 0.5 % | +379.67 s |
| language_detection | · lid.run | 1 | ok | 12.51 s | 0.5 % | +391.50 s |
| language_detection | · lid.run | 1 | ok | 11.91 s | 0.5 % | +404.02 s |
| language_detection | · lid.run | 1 | ok | 11.03 s | 0.5 % | +415.94 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | 0.4 % | +426.99 s |
| language_detection | · lid.run | 1 | ok | 11.24 s | 0.5 % | +437.33 s |
| language_detection | · lid.run | 1 | ok | 10.34 s | 0.4 % | +448.57 s |
| language_detection | · lid.run | 1 | ok | 11.57 s | 0.5 % | +458.92 s |
| language_detection | · lid.run | 1 | ok | 11.84 s | 0.5 % | +470.51 s |
| language_detection | · lid.run | 1 | ok | 11.90 s | 0.5 % | +482.36 s |
| language_detection | · lid.run | 1 | ok | 10.69 s | 0.5 % | +494.28 s |
| language_detection | · lid.run | 1 | ok | 11.42 s | 0.5 % | +504.99 s |
| language_detection | · lid.run | 1 | ok | 9.05 s | 0.4 % | +516.42 s |
| language_detection | · lid.run | 1 | ok | 11.37 s | 0.5 % | +525.48 s |
| language_detection | · lid.run | 1 | ok | 9.98 s | 0.4 % | +536.85 s |
| language_detection | · lid.run | 1 | ok | 11.45 s | 0.5 % | +546.84 s |
| language_detection | · lid.run | 1 | ok | 11.44 s | 0.5 % | +558.31 s |
| language_detection | · lid.run | 1 | ok | 10.77 s | 0.5 % | +569.77 s |
| language_detection | · lid.run | 1 | ok | 12.23 s | 0.5 % | +580.55 s |
| language_detection | · lid.run | 1 | ok | 10.94 s | 0.5 % | +592.78 s |
| language_detection | · lid.run | 1 | ok | 9.81 s | 0.4 % | +603.73 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 0.4 % | +613.54 s |
| language_detection | · lid.run | 1 | ok | 11.72 s | 0.5 % | +623.28 s |
| language_detection | · lid.run | 1 | ok | 11.21 s | 0.5 % | +635.01 s |
| language_detection | · lid.run | 1 | ok | 9.91 s | 0.4 % | +646.22 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 1503.86 s | 65.2 % | +656.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.96 s | 0.5 % | +656.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.32 s | 0.8 % | +668.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.91 s | 1.0 % | +685.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.66 s | 0.9 % | +708.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.58 s | 0.5 % | +728.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.92 s | 0.7 % | +740.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.92 s | 1.3 % | +757.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.27 s | 1.0 % | +787.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.29 s | 0.6 % | +809.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.46 s | 0.5 % | +824.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.63 s | 0.5 % | +835.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.44 s | 0.7 % | +847.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.66 s | 0.9 % | +863.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.37 s | 1.0 % | +885.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.10 s | 0.7 % | +907.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.53 s | 0.7 % | +922.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 40.93 s | 1.8 % | +939.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.74 s | 0.5 % | +980.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.38 s | 0.8 % | +992.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.65 s | 0.6 % | +1011.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 60.96 s | 2.6 % | +1025.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.53 s | 0.5 % | +1086.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.82 s | 0.6 % | +1097.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.08 s | 0.6 % | +1110.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 40.22 s | 1.7 % | +1123.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.37 s | 0.5 % | +1163.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 28.13 s | 1.2 % | +1176.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.95 s | 1.0 % | +1204.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.65 s | 0.9 % | +1226.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 25.67 s | 1.1 % | +1246.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 61.63 s | 2.7 % | +1272.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.73 s | 1.3 % | +1334.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.25 s | 0.8 % | +1364.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 102.26 s | 4.4 % | +1383.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 36.00 s | 1.6 % | +1485.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 32.29 s | 1.4 % | +1521.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 37.70 s | 1.6 % | +1553.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.29 s | 0.8 % | +1591.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.73 s | 0.8 % | +1609.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.81 s | 1.3 % | +1628.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 28.28 s | 1.2 % | +1658.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.07 s | 1.8 % | +1686.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 41.00 s | 1.8 % | +1727.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 32.26 s | 1.4 % | +1768.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 45.23 s | 2.0 % | +1801.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.75 s | 1.2 % | +1846.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.16 s | 0.6 % | +1874.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.61 s | 1.0 % | +1887.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.76 s | 0.9 % | +1911.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.03 s | 1.0 % | +1930.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.10 s | 0.9 % | +1952.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.50 s | 0.6 % | +1972.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.36 s | 0.5 % | +1986.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.37 s | 0.5 % | +1998.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 39.09 s | 1.7 % | +2011.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.71 s | 0.7 % | +2050.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.31 s | 0.6 % | +2066.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 25.70 s | 1.1 % | +2080.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.00 s | 0.5 % | +2106.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.90 s | 0.8 % | +2118.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.97 s | 1.0 % | +2135.97 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.07 s | 0.0 % | +2159.96 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +2160.03 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +2160.24 s |
| diarization_load | · diarization.load | 1 | ok | 6.91 s | 0.3 % | +2160.25 s |
| diarization_infer | · diarization.infer | 1 | ok | 113.83 s | 4.9 % | +2167.15 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.33 s | 0.0 % | +2280.98 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +2281.32 s |
| persist | · asr.persist | 1 | ok | 0.09 s | 0.0 % | +2281.33 s |
| other | worker_job | 1 | skipped | 0.01 s | — | +2281.47 s |
| queue | · asr.queue_wait | 1 | ok | 2281.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.48 s |
| queue | · asr.queue_wait | 1 | ok | 2281.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.48 s |
| queue | · asr.queue_wait | 1 | ok | 2281.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.49 s |
| queue | · asr.queue_wait | 1 | ok | 2281.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.49 s |
| queue | · asr.queue_wait | 1 | ok | 2281.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.50 s |
| queue | · asr.queue_wait | 1 | ok | 2281.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.50 s |
| queue | · asr.queue_wait | 1 | ok | 2281.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.51 s |
| queue | · asr.queue_wait | 1 | ok | 2281.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.51 s |
| queue | · asr.queue_wait | 1 | ok | 2281.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.51 s |
| queue | · asr.queue_wait | 1 | ok | 2281.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.52 s |
| queue | · asr.queue_wait | 1 | ok | 2281.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.52 s |
| queue | · asr.queue_wait | 1 | ok | 2281.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.53 s |
| queue | · asr.queue_wait | 1 | ok | 2281.52 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.53 s |
| queue | · asr.queue_wait | 1 | ok | 2281.52 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.54 s |
| queue | · asr.queue_wait | 1 | ok | 2281.53 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.54 s |
| queue | · asr.queue_wait | 1 | ok | 2281.53 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.55 s |
| queue | · asr.queue_wait | 1 | ok | 2281.54 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.55 s |
| queue | · asr.queue_wait | 1 | ok | 2281.54 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.56 s |
| queue | · asr.queue_wait | 1 | ok | 2281.55 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.56 s |
| queue | · asr.queue_wait | 1 | ok | 2281.55 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.57 s |
| queue | · asr.queue_wait | 1 | ok | 2281.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.57 s |
| queue | · asr.queue_wait | 1 | ok | 2281.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.57 s |
| queue | · asr.queue_wait | 1 | ok | 2281.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.58 s |
| queue | · asr.queue_wait | 1 | ok | 2281.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.58 s |
| queue | · asr.queue_wait | 1 | ok | 2281.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.59 s |
| queue | · asr.queue_wait | 1 | ok | 2281.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.59 s |
| queue | · asr.queue_wait | 1 | ok | 2281.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.02 s | — | +2281.60 s |
| queue | · asr.queue_wait | 1 | ok | 2281.59 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.62 s |
| queue | · asr.queue_wait | 1 | ok | 2281.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.63 s |
| queue | · asr.queue_wait | 1 | ok | 2281.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.63 s |
| queue | · asr.queue_wait | 1 | ok | 2281.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.64 s |
| queue | · asr.queue_wait | 1 | ok | 2281.63 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.64 s |
| queue | · asr.queue_wait | 1 | ok | 2281.63 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.65 s |
| queue | · asr.queue_wait | 1 | ok | 2281.64 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.65 s |
| queue | · asr.queue_wait | 1 | ok | 2281.64 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2281.66 s |
| queue | · asr.queue_wait | 1 | ok | 2281.65 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.83 s | 0.0 % | +2292.46 s |
| other | notes.generate | 1 | ok | 14.02 s | — | +2293.32 s |
| llm_call | · llm.note_write | 1 | ok | 13.79 s | 0.6 % | +2293.45 s |

Spans under a redelivered pickup of a finished job are off the critical path.

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
| asr.chunk | faster_whisper | 3.64 s | 13.65 s | 3.746 |
| asr.chunk | faster_whisper | 30.00 s | 60.96 s | 2.032 |
| asr.chunk | faster_whisper | 1.52 s | 11.53 s | 7.609 |
| asr.chunk | faster_whisper | 1.56 s | 12.82 s | 8.197 |
| asr.chunk | faster_whisper | 3.90 s | 13.08 s | 3.355 |
| asr.chunk | faster_whisper | 30.00 s | 40.22 s | 1.341 |
| asr.chunk | faster_whisper | 1.90 s | 12.37 s | 6.512 |
| asr.chunk | faster_whisper | 20.00 s | 28.13 s | 1.407 |
| asr.chunk | faster_whisper | 14.68 s | 21.95 s | 1.495 |
| asr.chunk | faster_whisper | 5.08 s | 20.65 s | 4.061 |
| asr.chunk | faster_whisper | 14.40 s | 25.67 s | 1.783 |
| asr.chunk | faster_whisper | 29.95 s | 61.63 s | 2.058 |
| asr.chunk | faster_whisper | 19.68 s | 29.73 s | 1.511 |
| asr.chunk | faster_whisper | 18.81 s | 19.25 s | 1.023 |
| asr.chunk | faster_whisper | 30.00 s | 102.26 s | 3.409 |
| asr.chunk | faster_whisper | 30.00 s | 36.00 s | 1.200 |
| asr.chunk | faster_whisper | 30.00 s | 32.29 s | 1.076 |
| asr.chunk | faster_whisper | 22.54 s | 37.69 s | 1.672 |
| asr.chunk | faster_whisper | 2.17 s | 18.29 s | 8.423 |
| asr.chunk | faster_whisper | 8.64 s | 18.73 s | 2.168 |
| asr.chunk | faster_whisper | 21.82 s | 29.80 s | 1.366 |
| asr.chunk | faster_whisper | 15.84 s | 28.28 s | 1.786 |
| asr.chunk | faster_whisper | 30.00 s | 41.07 s | 1.369 |
| asr.chunk | faster_whisper | 30.00 s | 41.00 s | 1.367 |
| asr.chunk | faster_whisper | 30.00 s | 32.26 s | 1.075 |
| asr.chunk | faster_whisper | 30.00 s | 45.23 s | 1.508 |
| asr.chunk | faster_whisper | 20.44 s | 27.75 s | 1.357 |
| asr.chunk | faster_whisper | 1.12 s | 13.16 s | 11.790 |
| asr.chunk | faster_whisper | 15.13 s | 23.61 s | 1.560 |
| asr.chunk | faster_whisper | 9.47 s | 19.76 s | 2.087 |
| asr.chunk | faster_whisper | 18.08 s | 22.03 s | 1.219 |
| asr.chunk | faster_whisper | 20.03 s | 20.10 s | 1.004 |
| asr.chunk | faster_whisper | 6.46 s | 13.50 s | 2.090 |
| asr.chunk | faster_whisper | 4.44 s | 12.36 s | 2.781 |
| asr.chunk | faster_whisper | 3.87 s | 12.37 s | 3.198 |
| asr.chunk | faster_whisper | 30.00 s | 39.09 s | 1.303 |
| asr.chunk | faster_whisper | 10.80 s | 15.71 s | 1.455 |
| asr.chunk | faster_whisper | 8.28 s | 14.31 s | 1.727 |
| asr.chunk | faster_whisper | 29.34 s | 25.70 s | 0.876 |
| asr.chunk | faster_whisper | 2.17 s | 12.00 s | 5.524 |
| asr.chunk | faster_whisper | 2.08 s | 17.90 s | 8.621 |
| asr.chunk | faster_whisper | 9.15 s | 23.97 s | 2.619 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 866.14 s |
| audio duration | 900.00 s |
| reprocessing ratio | 0.962 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 6.91 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 113.83 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 5 | 9.7 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.83 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 13.79 s | 3,759 | 0 | 0 | 1,000 | — (not_supported) |
| **total** |  | 2 |  |  | 14.62 s | 3,771 | 0 | 0 | 1,006 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,451,648,512 B (2.28 GiB) → 2,354,130,944 B (2.19 GiB) |
| swap used | 740,835,328 B (0.69 GiB) → 1,059,717,120 B (0.99 GiB) |
| memory pressure | some_avg10=0.07 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.08 s |
| telemetry buffer peak | 1,470 B |

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

- Top critical-path stages: asr_primary 1503.83 s (65.2 %); language_detection 597.60 s (25.9 %); diarization_infer 113.83 s (4.9 %).
- Reprocessing ratio: 0.962.
- Cold loads: vad.model 2.98 s; diarization.load 6.91 s.
- Queue wait: 21.83 s.
- LLM latency share of wall: 0.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Hypothesis: ASR dominates (rtf 2.564, asr_primary 65.2 % of wall); consider a smaller model, quantization or a lower beam.

Checked, did not fire: `asr_device_configured`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
