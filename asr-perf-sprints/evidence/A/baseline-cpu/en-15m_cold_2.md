# Diagnostics — recording 7aeb8ffd-25d5-42ad-8ef6-e62d2b1a1f0a

Run `241c8b9d-6482-45b9-9a6d-a2dc70a96b1e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7aeb8ffd-25d5-42ad-8ef6-e62d2b1a1f0a |
| processing_run_id | 241c8b9d-6482-45b9-9a6d-a2dc70a96b1e |
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
| audio duration | 892.39 s |
| processing_wall_seconds | 2102.23 s |
| rtf | 2.356 |
| speedup | 0.424 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.39 s | 0.0 % | -0.40 s |
| capture_input | asr.submit.probe | 1 | ok | 0.15 s | 0.0 % | -0.29 s |
| other | worker_job | 1 | ok | 2056.13 s | — | +28.38 s |
| queue | · asr.queue_wait | 1 | ok | 28.37 s | 1.3 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.16 s | 0.1 % | +28.39 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +29.55 s |
| model_init | · vad.model | 1 | ok | 3.18 s | 0.2 % | +29.55 s |
| vad | · vad.speech_runs | 1 | ok | 36.60 s | 1.7 % | +32.73 s |
| language_detection | · lid.recording | 1 | ok | 10.39 s | 0.5 % | +69.35 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 0.4 % | +79.74 s |
| language_detection | · lid.run | 1 | ok | 10.42 s | 0.5 % | +88.88 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 0.4 % | +99.31 s |
| language_detection | · lid.run | 1 | ok | 8.45 s | 0.4 % | +108.46 s |
| language_detection | · lid.run | 1 | ok | 9.10 s | 0.4 % | +116.91 s |
| language_detection | · lid.run | 1 | ok | 8.56 s | 0.4 % | +126.01 s |
| language_detection | · lid.run | 1 | ok | 8.83 s | 0.4 % | +134.58 s |
| language_detection | · lid.run | 1 | ok | 8.36 s | 0.4 % | +143.42 s |
| language_detection | · lid.run | 1 | ok | 8.76 s | 0.4 % | +151.78 s |
| language_detection | · lid.run | 1 | ok | 8.90 s | 0.4 % | +160.55 s |
| language_detection | · lid.run | 1 | ok | 8.98 s | 0.4 % | +169.45 s |
| language_detection | · lid.run | 1 | ok | 8.77 s | 0.4 % | +178.43 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | 0.4 % | +187.20 s |
| language_detection | · lid.run | 1 | ok | 8.86 s | 0.4 % | +196.22 s |
| language_detection | · lid.run | 1 | ok | 9.26 s | 0.4 % | +205.08 s |
| language_detection | · lid.run | 1 | ok | 9.77 s | 0.5 % | +214.34 s |
| language_detection | · lid.run | 1 | ok | 8.63 s | 0.4 % | +224.12 s |
| language_detection | · lid.run | 1 | ok | 8.94 s | 0.4 % | +232.76 s |
| language_detection | · lid.run | 1 | ok | 8.80 s | 0.4 % | +241.69 s |
| language_detection | · lid.run | 1 | ok | 9.04 s | 0.4 % | +250.50 s |
| language_detection | · lid.run | 1 | ok | 8.74 s | 0.4 % | +259.54 s |
| language_detection | · lid.run | 1 | ok | 8.88 s | 0.4 % | +268.28 s |
| language_detection | · lid.run | 1 | ok | 8.29 s | 0.4 % | +277.16 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 0.4 % | +285.45 s |
| language_detection | · lid.run | 1 | ok | 9.72 s | 0.5 % | +294.38 s |
| language_detection | · lid.run | 1 | ok | 9.27 s | 0.4 % | +304.11 s |
| language_detection | · lid.run | 1 | ok | 9.97 s | 0.5 % | +313.39 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 0.4 % | +323.37 s |
| language_detection | · lid.run | 1 | ok | 10.86 s | 0.5 % | +332.48 s |
| language_detection | · lid.run | 1 | ok | 9.45 s | 0.4 % | +343.36 s |
| language_detection | · lid.run | 1 | ok | 9.03 s | 0.4 % | +352.82 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 0.4 % | +361.84 s |
| language_detection | · lid.run | 1 | ok | 9.13 s | 0.4 % | +370.87 s |
| language_detection | · lid.run | 1 | ok | 8.60 s | 0.4 % | +380.00 s |
| language_detection | · lid.run | 1 | ok | 9.97 s | 0.5 % | +388.61 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 0.4 % | +398.58 s |
| language_detection | · lid.run | 1 | ok | 9.19 s | 0.4 % | +407.69 s |
| language_detection | · lid.run | 1 | ok | 9.41 s | 0.4 % | +416.89 s |
| language_detection | · lid.run | 1 | ok | 9.63 s | 0.5 % | +426.30 s |
| language_detection | · lid.run | 1 | ok | 8.62 s | 0.4 % | +435.94 s |
| language_detection | · lid.run | 1 | ok | 9.17 s | 0.4 % | +444.56 s |
| language_detection | · lid.run | 1 | ok | 9.25 s | 0.4 % | +453.73 s |
| language_detection | · lid.run | 1 | ok | 9.34 s | 0.4 % | +462.99 s |
| language_detection | · lid.run | 1 | ok | 8.79 s | 0.4 % | +472.33 s |
| language_detection | · lid.run | 1 | ok | 8.80 s | 0.4 % | +481.13 s |
| language_detection | · lid.run | 1 | ok | 8.91 s | 0.4 % | +489.93 s |
| language_detection | · lid.run | 1 | ok | 8.91 s | 0.4 % | +498.84 s |
| language_detection | · lid.run | 1 | ok | 8.78 s | 0.4 % | +507.76 s |
| language_detection | · lid.run | 1 | ok | 8.82 s | 0.4 % | +516.54 s |
| language_detection | · lid.run | 1 | ok | 8.37 s | 0.4 % | +525.36 s |
| language_detection | · lid.run | 1 | ok | 8.43 s | 0.4 % | +533.73 s |
| language_detection | · lid.run | 1 | ok | 8.80 s | 0.4 % | +542.17 s |
| language_detection | · lid.run | 1 | ok | 9.07 s | 0.4 % | +550.97 s |
| language_detection | · lid.run | 1 | ok | 8.59 s | 0.4 % | +560.04 s |
| language_detection | · lid.run | 1 | ok | 8.80 s | 0.4 % | +568.63 s |
| language_detection | · lid.run | 1 | ok | 10.46 s | 0.5 % | +577.44 s |
| language_detection | · lid.run | 1 | ok | 9.31 s | 0.4 % | +587.91 s |
| language_detection | · lid.run | 1 | ok | 8.85 s | 0.4 % | +597.22 s |
| language_detection | · lid.run | 1 | ok | 8.71 s | 0.4 % | +606.07 s |
| language_detection | · lid.run | 1 | ok | 8.96 s | 0.4 % | +614.79 s |
| language_detection | · lid.run | 1 | ok | 8.74 s | 0.4 % | +623.75 s |
| language_detection | · lid.run | 1 | ok | 8.57 s | 0.4 % | +632.50 s |
| language_detection | · lid.run | 1 | ok | 9.04 s | 0.4 % | +641.07 s |
| language_detection | · lid.run | 1 | ok | 8.92 s | 0.4 % | +650.11 s |
| language_detection | · lid.run | 1 | ok | 9.20 s | 0.4 % | +659.04 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 0.4 % | +668.24 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 0.4 % | +677.39 s |
| language_detection | · lid.run | 1 | ok | 8.83 s | 0.4 % | +686.51 s |
| language_detection | · lid.run | 1 | ok | 10.96 s | 0.5 % | +695.34 s |
| language_detection | · lid.run | 1 | ok | 10.09 s | 0.5 % | +706.33 s |
| language_detection | · lid.run | 1 | ok | 9.26 s | 0.4 % | +716.42 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | 0.5 % | +725.68 s |
| language_detection | · lid.run | 1 | ok | 9.07 s | 0.4 % | +736.02 s |
| language_detection | · lid.run | 1 | ok | 9.07 s | 0.4 % | +745.09 s |
| language_detection | · lid.run | 1 | ok | 8.95 s | 0.4 % | +754.16 s |
| language_detection | · lid.run | 1 | ok | 10.57 s | 0.5 % | +763.12 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 0.4 % | +773.69 s |
| language_detection | · lid.run | 1 | ok | 8.38 s | 0.4 % | +782.63 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 1188.84 s | 56.6 % | +791.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.62 s | 0.8 % | +791.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.01 s | 0.6 % | +807.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.46 s | 0.6 % | +820.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.23 s | 0.8 % | +834.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.89 s | 0.6 % | +851.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.37 s | 0.7 % | +863.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.92 s | 0.6 % | +877.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.75 s | 0.8 % | +890.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.49 s | 0.7 % | +907.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.70 s | 0.8 % | +921.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.76 s | 0.7 % | +938.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.75 s | 0.7 % | +953.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.24 s | 0.6 % | +969.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.78 s | 0.7 % | +982.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.61 s | 1.0 % | +996.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.61 s | 0.8 % | +1017.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.15 s | 0.6 % | +1035.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.93 s | 0.7 % | +1047.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.31 s | 0.6 % | +1062.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.02 s | 1.0 % | +1075.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.95 s | 0.8 % | +1097.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.50 s | 0.5 % | +1114.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.06 s | 0.7 % | +1125.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.78 s | 0.6 % | +1139.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.37 s | 0.8 % | +1152.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.05 s | 0.7 % | +1168.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.50 s | 0.8 % | +1182.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.58 s | 0.6 % | +1198.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.12 s | 0.8 % | +1212.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.73 s | 0.7 % | +1229.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.99 s | 0.7 % | +1245.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.86 s | 0.8 % | +1260.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.66 s | 0.6 % | +1276.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.63 s | 0.5 % | +1288.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.12 s | 0.8 % | +1299.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.74 s | 0.7 % | +1316.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.54 s | 0.7 % | +1331.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.70 s | 0.6 % | +1346.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.77 s | 0.9 % | +1359.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.41 s | 0.6 % | +1379.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.14 s | 0.7 % | +1391.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.21 s | 0.7 % | +1405.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.92 s | 0.6 % | +1421.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.77 s | 0.6 % | +1433.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.19 s | 0.7 % | +1445.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.57 s | 0.6 % | +1461.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.72 s | 0.7 % | +1473.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.72 s | 0.7 % | +1488.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.89 s | 0.6 % | +1503.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.12 s | 0.6 % | +1515.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.40 s | 0.6 % | +1529.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.95 s | 0.6 % | +1541.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.32 s | 0.6 % | +1554.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.14 s | 0.5 % | +1566.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.12 s | 0.8 % | +1577.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.72 s | 0.7 % | +1594.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.87 s | 0.5 % | +1607.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.35 s | 0.7 % | +1618.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.67 s | 0.7 % | +1632.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.73 s | 0.6 % | +1648.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.93 s | 0.8 % | +1661.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.41 s | 0.6 % | +1678.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.14 s | 0.8 % | +1691.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.09 s | 0.7 % | +1707.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.66 s | 0.6 % | +1721.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.32 s | 0.8 % | +1735.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.30 s | 0.6 % | +1751.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.63 s | 0.6 % | +1765.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.85 s | 0.6 % | +1777.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.22 s | 0.7 % | +1790.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.81 s | 0.7 % | +1805.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.67 s | 0.7 % | +1819.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.60 s | 0.8 % | +1833.48 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.30 s | 0.6 % | +1851.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.33 s | 0.7 % | +1864.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.23 s | 0.7 % | +1879.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 26.90 s | 1.3 % | +1893.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.08 s | 0.6 % | +1920.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.77 s | 0.6 % | +1933.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.09 s | 0.6 % | +1946.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.33 s | 0.5 % | +1958.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.67 s | 0.5 % | +1969.15 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +1979.83 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1979.87 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1979.99 s |
| diarization_load | · diarization.load | 1 | ok | 3.05 s | 0.1 % | +1979.99 s |
| diarization_infer | · diarization.infer | 1 | ok | 101.10 s | 4.8 % | +1983.04 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.28 s | 0.0 % | +2084.14 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +2084.42 s |
| persist | · asr.persist | 1 | ok | 0.06 s | 0.0 % | +2084.43 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.52 s |
| queue | · asr.queue_wait | 1 | ok | 2084.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.53 s |
| queue | · asr.queue_wait | 1 | ok | 2084.52 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.53 s |
| queue | · asr.queue_wait | 1 | ok | 2084.52 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.53 s |
| queue | · asr.queue_wait | 1 | ok | 2084.53 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.54 s |
| queue | · asr.queue_wait | 1 | ok | 2084.53 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.54 s |
| queue | · asr.queue_wait | 1 | ok | 2084.54 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.55 s |
| queue | · asr.queue_wait | 1 | ok | 2084.54 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.55 s |
| queue | · asr.queue_wait | 1 | ok | 2084.55 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.56 s |
| queue | · asr.queue_wait | 1 | ok | 2084.55 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.56 s |
| queue | · asr.queue_wait | 1 | ok | 2084.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.57 s |
| queue | · asr.queue_wait | 1 | ok | 2084.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.57 s |
| queue | · asr.queue_wait | 1 | ok | 2084.56 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.58 s |
| queue | · asr.queue_wait | 1 | ok | 2084.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.58 s |
| queue | · asr.queue_wait | 1 | ok | 2084.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.58 s |
| queue | · asr.queue_wait | 1 | ok | 2084.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.59 s |
| queue | · asr.queue_wait | 1 | ok | 2084.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.59 s |
| queue | · asr.queue_wait | 1 | ok | 2084.59 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.60 s |
| queue | · asr.queue_wait | 1 | ok | 2084.59 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.60 s |
| queue | · asr.queue_wait | 1 | ok | 2084.59 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.60 s |
| queue | · asr.queue_wait | 1 | ok | 2084.60 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.61 s |
| queue | · asr.queue_wait | 1 | ok | 2084.60 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.61 s |
| queue | · asr.queue_wait | 1 | ok | 2084.61 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.62 s |
| queue | · asr.queue_wait | 1 | ok | 2084.61 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.62 s |
| queue | · asr.queue_wait | 1 | ok | 2084.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.63 s |
| queue | · asr.queue_wait | 1 | ok | 2084.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.63 s |
| queue | · asr.queue_wait | 1 | ok | 2084.62 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.63 s |
| queue | · asr.queue_wait | 1 | ok | 2084.63 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.64 s |
| queue | · asr.queue_wait | 1 | ok | 2084.63 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.02 s | — | +2084.64 s |
| queue | · asr.queue_wait | 1 | ok | 2084.64 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.67 s |
| queue | · asr.queue_wait | 1 | ok | 2084.66 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.67 s |
| queue | · asr.queue_wait | 1 | ok | 2084.66 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.67 s |
| queue | · asr.queue_wait | 1 | ok | 2084.67 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2084.68 s |
| queue | · asr.queue_wait | 1 | ok | 2084.67 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.78 s | 0.0 % | +2086.56 s |
| other | notes.generate | 1 | ok | 14.88 s | — | +2087.35 s |
| llm_call | · llm.note_write | 1 | ok | 14.73 s | 0.7 % | +2087.42 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 798.08 s | 82 | 1.28 s | 8.68 s | 30.00 s |

### Language checks

Language checks: 79.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 10.39 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 9.14 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 10.42 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 9.14 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 8.45 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 9.10 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 8.56 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 8.83 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 8.36 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 8.76 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 8.90 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 8.98 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 8.77 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 9.00 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 8.86 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 9.26 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 9.77 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 8.63 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 8.94 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 8.80 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 9.04 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 8.74 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 8.88 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 8.29 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 8.93 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 9.72 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 9.27 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 9.97 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 9.11 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 10.86 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 9.45 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 9.03 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 9.02 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 9.13 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 8.60 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 9.97 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 9.11 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 9.19 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 9.41 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 9.63 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 8.62 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 9.17 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 9.25 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 9.34 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 8.79 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 8.80 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 8.91 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 8.91 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 8.78 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 8.82 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 8.37 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 8.43 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 8.80 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 9.07 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 8.59 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 8.80 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 10.46 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 9.31 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 8.85 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 8.71 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 8.96 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 8.74 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 8.57 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 9.04 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 8.92 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 9.20 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 9.14 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 9.11 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 8.83 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 10.96 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 10.09 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 9.26 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 10.33 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 9.07 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 9.07 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 8.95 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 10.57 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 8.93 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 8.38 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 16.62 s | 1.080 |
| asr.chunk | faster_whisper | 8.73 s | 13.01 s | 1.490 |
| asr.chunk | faster_whisper | 4.28 s | 13.46 s | 3.141 |
| asr.chunk | faster_whisper | 16.38 s | 17.23 s | 1.052 |
| asr.chunk | faster_whisper | 4.54 s | 11.89 s | 2.620 |
| asr.chunk | faster_whisper | 13.53 s | 14.37 s | 1.062 |
| asr.chunk | faster_whisper | 8.12 s | 12.92 s | 1.590 |
| asr.chunk | faster_whisper | 10.59 s | 16.75 s | 1.582 |
| asr.chunk | faster_whisper | 7.90 s | 14.49 s | 1.834 |
| asr.chunk | faster_whisper | 13.28 s | 16.70 s | 1.258 |
| asr.chunk | faster_whisper | 4.48 s | 14.76 s | 3.298 |
| asr.chunk | faster_whisper | 13.12 s | 15.75 s | 1.201 |
| asr.chunk | faster_whisper | 7.48 s | 13.24 s | 1.770 |
| asr.chunk | faster_whisper | 6.24 s | 13.78 s | 2.209 |
| asr.chunk | faster_whisper | 28.38 s | 21.61 s | 0.761 |
| asr.chunk | faster_whisper | 16.28 s | 17.61 s | 1.081 |
| asr.chunk | faster_whisper | 7.04 s | 12.15 s | 1.726 |
| asr.chunk | faster_whisper | 9.63 s | 14.93 s | 1.550 |
| asr.chunk | faster_whisper | 2.49 s | 13.31 s | 5.341 |
| asr.chunk | faster_whisper | 24.16 s | 22.02 s | 0.911 |
| asr.chunk | faster_whisper | 16.64 s | 16.95 s | 1.019 |
| asr.chunk | faster_whisper | 1.28 s | 10.50 s | 8.226 |
| asr.chunk | faster_whisper | 11.71 s | 14.06 s | 1.201 |
| asr.chunk | faster_whisper | 6.46 s | 12.78 s | 1.978 |
| asr.chunk | faster_whisper | 15.71 s | 16.37 s | 1.042 |
| asr.chunk | faster_whisper | 8.73 s | 14.05 s | 1.609 |
| asr.chunk | faster_whisper | 13.47 s | 16.50 s | 1.225 |
| asr.chunk | faster_whisper | 6.84 s | 13.58 s | 1.984 |
| asr.chunk | faster_whisper | 17.82 s | 17.12 s | 0.961 |
| asr.chunk | faster_whisper | 11.61 s | 15.73 s | 1.355 |
| asr.chunk | faster_whisper | 11.10 s | 14.98 s | 1.350 |
| asr.chunk | faster_whisper | 12.41 s | 15.86 s | 1.278 |
| asr.chunk | faster_whisper | 6.24 s | 12.66 s | 2.030 |
| asr.chunk | faster_whisper | 1.82 s | 10.63 s | 5.839 |
| asr.chunk | faster_whisper | 13.85 s | 17.12 s | 1.236 |
| asr.chunk | faster_whisper | 12.44 s | 14.74 s | 1.184 |
| asr.chunk | faster_whisper | 10.84 s | 15.54 s | 1.433 |
| asr.chunk | faster_whisper | 8.96 s | 12.70 s | 1.418 |
| asr.chunk | faster_whisper | 20.76 s | 19.77 s | 0.952 |
| asr.chunk | faster_whisper | 5.98 s | 12.41 s | 2.076 |
| asr.chunk | faster_whisper | 7.77 s | 14.14 s | 1.820 |
| asr.chunk | faster_whisper | 11.87 s | 15.21 s | 1.281 |
| asr.chunk | faster_whisper | 4.48 s | 11.92 s | 2.663 |
| asr.chunk | faster_whisper | 5.53 s | 12.77 s | 2.309 |
| asr.chunk | faster_whisper | 11.64 s | 15.19 s | 1.305 |
| asr.chunk | faster_whisper | 3.00 s | 12.57 s | 4.184 |
| asr.chunk | faster_whisper | 11.39 s | 14.72 s | 1.292 |
| asr.chunk | faster_whisper | 11.77 s | 14.72 s | 1.250 |
| asr.chunk | faster_whisper | 4.48 s | 12.89 s | 2.880 |
| asr.chunk | faster_whisper | 8.64 s | 13.12 s | 1.520 |
| asr.chunk | faster_whisper | 6.01 s | 12.40 s | 2.062 |
| asr.chunk | faster_whisper | 8.03 s | 12.95 s | 1.613 |
| asr.chunk | faster_whisper | 2.56 s | 12.32 s | 4.819 |
| asr.chunk | faster_whisper | 2.49 s | 11.14 s | 4.471 |
| asr.chunk | faster_whisper | 13.44 s | 16.12 s | 1.200 |
| asr.chunk | faster_whisper | 7.58 s | 13.72 s | 1.811 |
| asr.chunk | faster_whisper | 2.68 s | 10.87 s | 4.050 |
| asr.chunk | faster_whisper | 8.83 s | 14.35 s | 1.626 |
| asr.chunk | faster_whisper | 14.14 s | 15.67 s | 1.108 |
| asr.chunk | faster_whisper | 8.25 s | 12.73 s | 1.543 |
| asr.chunk | faster_whisper | 17.34 s | 16.93 s | 0.976 |
| asr.chunk | faster_whisper | 6.24 s | 13.41 s | 2.150 |
| asr.chunk | faster_whisper | 13.85 s | 16.14 s | 1.165 |
| asr.chunk | faster_whisper | 6.97 s | 14.09 s | 2.021 |
| asr.chunk | faster_whisper | 8.48 s | 13.66 s | 1.612 |
| asr.chunk | faster_whisper | 15.45 s | 16.32 s | 1.056 |
| asr.chunk | faster_whisper | 5.88 s | 13.30 s | 2.261 |
| asr.chunk | faster_whisper | 7.20 s | 12.63 s | 1.755 |
| asr.chunk | faster_whisper | 8.09 s | 12.85 s | 1.588 |
| asr.chunk | faster_whisper | 11.80 s | 15.22 s | 1.289 |
| asr.chunk | faster_whisper | 7.48 s | 13.81 s | 1.846 |
| asr.chunk | faster_whisper | 9.18 s | 13.67 s | 1.489 |
| asr.chunk | faster_whisper | 12.06 s | 17.60 s | 1.460 |
| asr.chunk | faster_whisper | 6.33 s | 13.30 s | 2.101 |
| asr.chunk | faster_whisper | 9.63 s | 15.33 s | 1.592 |
| asr.chunk | faster_whisper | 10.81 s | 14.23 s | 1.316 |
| asr.chunk | faster_whisper | 30.00 s | 26.90 s | 0.897 |
| asr.chunk | faster_whisper | 4.24 s | 13.08 s | 3.089 |
| asr.chunk | faster_whisper | 5.12 s | 12.77 s | 2.495 |
| asr.chunk | faster_whisper | 6.91 s | 12.09 s | 1.750 |
| asr.chunk | faster_whisper | 1.76 s | 10.33 s | 5.881 |
| asr.chunk | faster_whisper | 1.98 s | 10.67 s | 5.391 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 798.08 s |
| audio duration | 892.39 s |
| reprocessing ratio | 0.894 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 3.05 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 101.10 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.78 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 14.73 s | 4,887 | 0 | 0 | 995 | — (not_supported) |
| **total** |  | 2 |  |  | 15.51 s | 4,899 | 0 | 0 | 1,001 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,311,488 B (2.28 GiB) → 2,408,054,784 B (2.24 GiB) |
| swap used | 1,425,244,160 B (1.33 GiB) → 1,423,048,704 B (1.33 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.04 s |
| telemetry buffer peak | 1,607 B |

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

- Top critical-path stages: asr_primary 1188.82 s (56.6 %); language_detection 721.33 s (34.3 %); diarization_infer 101.10 s (4.8 %).
- Reprocessing ratio: 0.894.
- Cold loads: vad.model 3.18 s; diarization.load 3.05 s.
- Queue wait: 28.37 s.
- LLM latency share of wall: 0.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
