# Diagnostics — recording df27789b-54c9-4dc0-910b-e92a1a67752b

Run `5535916e-8c86-438c-a825-220f6c818592` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | df27789b-54c9-4dc0-910b-e92a1a67752b |
| processing_run_id | 5535916e-8c86-438c-a825-220f6c818592 |
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
| processing_wall_seconds | 2040.51 s |
| rtf | 2.287 |
| speedup | 0.437 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.31 s | 0.0 % | -0.31 s |
| capture_input | asr.submit.probe | 1 | ok | 0.14 s | 0.0 % | -0.22 s |
| other | worker_job | 1 | ok | 2009.60 s | — | +13.96 s |
| queue | · asr.queue_wait | 1 | ok | 13.96 s | 0.7 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.87 s | 0.0 % | +13.98 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +14.85 s |
| model_init | · vad.model | 1 | ok | 1.45 s | 0.1 % | +14.85 s |
| vad | · vad.speech_runs | 1 | ok | 17.15 s | 0.8 % | +16.29 s |
| language_detection | · lid.recording | 1 | ok | 5.54 s | 0.3 % | +33.45 s |
| language_detection | · lid.run | 1 | ok | 5.79 s | 0.3 % | +38.99 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.3 % | +44.78 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.3 % | +50.56 s |
| language_detection | · lid.run | 1 | ok | 5.35 s | 0.3 % | +56.18 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 0.3 % | +61.53 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 0.3 % | +67.12 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 0.3 % | +73.20 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.3 % | +78.94 s |
| language_detection | · lid.run | 1 | ok | 5.76 s | 0.3 % | +84.52 s |
| language_detection | · lid.run | 1 | ok | 5.76 s | 0.3 % | +90.29 s |
| language_detection | · lid.run | 1 | ok | 5.84 s | 0.3 % | +96.05 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.3 % | +101.89 s |
| language_detection | · lid.run | 1 | ok | 6.16 s | 0.3 % | +107.55 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 0.3 % | +113.71 s |
| language_detection | · lid.run | 1 | ok | 5.95 s | 0.3 % | +119.69 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 0.3 % | +125.64 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.3 % | +131.61 s |
| language_detection | · lid.run | 1 | ok | 6.26 s | 0.3 % | +137.18 s |
| language_detection | · lid.run | 1 | ok | 5.98 s | 0.3 % | +143.44 s |
| language_detection | · lid.run | 1 | ok | 6.20 s | 0.3 % | +149.43 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.3 % | +155.64 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.3 % | +161.27 s |
| language_detection | · lid.run | 1 | ok | 6.36 s | 0.3 % | +167.21 s |
| language_detection | · lid.run | 1 | ok | 6.08 s | 0.3 % | +173.58 s |
| language_detection | · lid.run | 1 | ok | 5.71 s | 0.3 % | +179.66 s |
| language_detection | · lid.run | 1 | ok | 6.17 s | 0.3 % | +185.37 s |
| language_detection | · lid.run | 1 | ok | 6.56 s | 0.3 % | +191.54 s |
| language_detection | · lid.run | 1 | ok | 6.57 s | 0.3 % | +198.11 s |
| language_detection | · lid.run | 1 | ok | 5.92 s | 0.3 % | +204.68 s |
| language_detection | · lid.run | 1 | ok | 6.73 s | 0.3 % | +210.60 s |
| language_detection | · lid.run | 1 | ok | 6.22 s | 0.3 % | +217.34 s |
| language_detection | · lid.run | 1 | ok | 5.83 s | 0.3 % | +223.56 s |
| language_detection | · lid.run | 1 | ok | 10.74 s | 0.5 % | +229.39 s |
| language_detection | · lid.run | 1 | ok | 17.36 s | 0.9 % | +240.16 s |
| language_detection | · lid.run | 1 | ok | 23.60 s | 1.2 % | +257.53 s |
| language_detection | · lid.run | 1 | ok | 16.06 s | 0.8 % | +281.15 s |
| language_detection | · lid.run | 1 | ok | 11.42 s | 0.6 % | +297.22 s |
| language_detection | · lid.run | 1 | ok | 10.49 s | 0.5 % | +308.66 s |
| language_detection | · lid.run | 1 | ok | 10.17 s | 0.5 % | +319.16 s |
| language_detection | · lid.run | 1 | ok | 8.66 s | 0.4 % | +329.34 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 0.4 % | +338.00 s |
| language_detection | · lid.run | 1 | ok | 8.43 s | 0.4 % | +347.15 s |
| language_detection | · lid.run | 1 | ok | 9.14 s | 0.4 % | +355.58 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | 0.5 % | +364.72 s |
| language_detection | · lid.run | 1 | ok | 9.31 s | 0.5 % | +375.05 s |
| language_detection | · lid.run | 1 | ok | 9.02 s | 0.4 % | +384.37 s |
| language_detection | · lid.run | 1 | ok | 8.71 s | 0.4 % | +393.40 s |
| language_detection | · lid.run | 1 | ok | 8.47 s | 0.4 % | +402.12 s |
| language_detection | · lid.run | 1 | ok | 9.30 s | 0.5 % | +410.59 s |
| language_detection | · lid.run | 1 | ok | 9.03 s | 0.4 % | +419.90 s |
| language_detection | · lid.run | 1 | ok | 9.88 s | 0.5 % | +428.93 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 0.5 % | +438.82 s |
| language_detection | · lid.run | 1 | ok | 9.82 s | 0.5 % | +448.04 s |
| language_detection | · lid.run | 1 | ok | 8.99 s | 0.4 % | +457.87 s |
| language_detection | · lid.run | 1 | ok | 9.21 s | 0.5 % | +466.87 s |
| language_detection | · lid.run | 1 | ok | 9.28 s | 0.5 % | +476.08 s |
| language_detection | · lid.run | 1 | ok | 9.27 s | 0.5 % | +485.36 s |
| language_detection | · lid.run | 1 | ok | 9.40 s | 0.5 % | +494.63 s |
| language_detection | · lid.run | 1 | ok | 8.72 s | 0.4 % | +504.04 s |
| language_detection | · lid.run | 1 | ok | 9.31 s | 0.5 % | +512.76 s |
| language_detection | · lid.run | 1 | ok | 10.81 s | 0.5 % | +522.07 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 0.4 % | +532.89 s |
| language_detection | · lid.run | 1 | ok | 9.49 s | 0.5 % | +541.82 s |
| language_detection | · lid.run | 1 | ok | 11.71 s | 0.6 % | +551.31 s |
| language_detection | · lid.run | 1 | ok | 8.93 s | 0.4 % | +563.03 s |
| language_detection | · lid.run | 1 | ok | 9.63 s | 0.5 % | +571.96 s |
| language_detection | · lid.run | 1 | ok | 9.81 s | 0.5 % | +581.60 s |
| language_detection | · lid.run | 1 | ok | 9.09 s | 0.4 % | +591.42 s |
| language_detection | · lid.run | 1 | ok | 8.58 s | 0.4 % | +600.51 s |
| language_detection | · lid.run | 1 | ok | 9.18 s | 0.4 % | +609.09 s |
| language_detection | · lid.run | 1 | ok | 9.43 s | 0.5 % | +618.27 s |
| language_detection | · lid.run | 1 | ok | 9.30 s | 0.5 % | +627.71 s |
| language_detection | · lid.run | 1 | ok | 9.12 s | 0.4 % | +637.02 s |
| language_detection | · lid.run | 1 | ok | 8.78 s | 0.4 % | +646.15 s |
| language_detection | · lid.run | 1 | ok | 9.00 s | 0.4 % | +654.93 s |
| language_detection | · lid.run | 1 | ok | 8.63 s | 0.4 % | +663.94 s |
| language_detection | · lid.run | 1 | ok | 10.05 s | 0.5 % | +672.57 s |
| language_detection | · lid.run | 1 | ok | 10.09 s | 0.5 % | +682.64 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 1225.07 s | 60.0 % | +692.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.49 s | 0.8 % | +692.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.49 s | 0.7 % | +709.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.24 s | 0.6 % | +723.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.58 s | 0.8 % | +735.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.13 s | 0.6 % | +752.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.07 s | 0.7 % | +764.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.68 s | 0.8 % | +779.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.14 s | 0.8 % | +795.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.32 s | 0.7 % | +811.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.99 s | 0.9 % | +825.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.83 s | 0.7 % | +843.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.12 s | 0.8 % | +857.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.87 s | 0.7 % | +873.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.66 s | 0.7 % | +887.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.72 s | 1.1 % | +901.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.46 s | 0.9 % | +923.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.83 s | 0.6 % | +941.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.02 s | 0.7 % | +954.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.97 s | 0.5 % | +968.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.49 s | 1.1 % | +979.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.77 s | 0.8 % | +1000.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.63 s | 0.5 % | +1017.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.83 s | 0.7 % | +1028.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.33 s | 0.7 % | +1043.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.77 s | 0.8 % | +1057.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.32 s | 0.8 % | +1074.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.39 s | 0.8 % | +1089.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.00 s | 0.8 % | +1106.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.59 s | 1.0 % | +1122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.27 s | 0.8 % | +1142.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.30 s | 0.8 % | +1158.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.15 s | 0.8 % | +1175.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.93 s | 0.6 % | +1191.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.82 s | 0.5 % | +1204.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.30 s | 0.7 % | +1215.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.58 s | 0.7 % | +1230.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.50 s | 0.7 % | +1245.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.25 s | 0.7 % | +1259.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 21.07 s | 1.0 % | +1273.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.61 s | 0.6 % | +1294.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.41 s | 0.7 % | +1307.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.44 s | 0.8 % | +1320.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.07 s | 0.6 % | +1336.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.82 s | 0.6 % | +1348.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.88 s | 0.8 % | +1360.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.54 s | 0.5 % | +1376.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.86 s | 0.9 % | +1386.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.96 s | 0.9 % | +1404.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.84 s | 0.6 % | +1423.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.90 s | 0.7 % | +1436.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.44 s | 0.7 % | +1450.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.21 s | 0.6 % | +1464.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.19 s | 0.6 % | +1477.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.77 s | 0.6 % | +1490.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.20 s | 0.8 % | +1501.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.11 s | 0.7 % | +1519.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.85 s | 0.6 % | +1533.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.51 s | 0.8 % | +1546.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.81 s | 0.8 % | +1561.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.86 s | 0.6 % | +1577.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.89 s | 0.8 % | +1590.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.06 s | 0.7 % | +1607.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.97 s | 0.8 % | +1621.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.75 s | 0.7 % | +1638.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.60 s | 0.7 % | +1651.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.50 s | 0.8 % | +1666.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.87 s | 0.6 % | +1683.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.88 s | 0.6 % | +1695.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.06 s | 0.6 % | +1708.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.50 s | 0.7 % | +1721.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.74 s | 0.7 % | +1736.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.64 s | 0.8 % | +1750.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.12 s | 0.8 % | +1765.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.16 s | 0.6 % | +1782.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.13 s | 0.7 % | +1796.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.16 s | 0.7 % | +1811.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 30.13 s | 1.5 % | +1826.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.51 s | 0.6 % | +1856.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.27 s | 0.7 % | +1868.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.31 s | 0.7 % | +1881.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.02 s | 0.6 % | +1894.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.17 s | 0.5 % | +1906.63 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +1917.81 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1917.85 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1917.97 s |
| diarization_load | · diarization.load | 1 | ok | 3.71 s | 0.2 % | +1917.97 s |
| diarization_infer | · diarization.infer | 1 | ok | 101.50 s | 5.0 % | +1921.68 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.28 s | 0.0 % | +2023.18 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +2023.46 s |
| persist | · asr.persist | 1 | ok | 0.09 s | 0.0 % | +2023.47 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.59 s |
| queue | · asr.queue_wait | 1 | ok | 2023.59 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.60 s |
| queue | · asr.queue_wait | 1 | ok | 2023.60 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.61 s |
| queue | · asr.queue_wait | 1 | ok | 2023.61 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.61 s |
| queue | · asr.queue_wait | 1 | ok | 2023.61 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.62 s |
| queue | · asr.queue_wait | 1 | ok | 2023.62 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.62 s |
| queue | · asr.queue_wait | 1 | ok | 2023.62 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.63 s |
| queue | · asr.queue_wait | 1 | ok | 2023.63 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.63 s |
| queue | · asr.queue_wait | 1 | ok | 2023.63 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.64 s |
| queue | · asr.queue_wait | 1 | ok | 2023.64 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.64 s |
| queue | · asr.queue_wait | 1 | ok | 2023.64 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.65 s |
| queue | · asr.queue_wait | 1 | ok | 2023.64 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.65 s |
| queue | · asr.queue_wait | 1 | ok | 2023.65 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.66 s |
| queue | · asr.queue_wait | 1 | ok | 2023.65 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.66 s |
| queue | · asr.queue_wait | 1 | ok | 2023.66 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.66 s |
| queue | · asr.queue_wait | 1 | ok | 2023.66 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.67 s |
| queue | · asr.queue_wait | 1 | ok | 2023.67 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.67 s |
| queue | · asr.queue_wait | 1 | ok | 2023.67 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.68 s |
| queue | · asr.queue_wait | 1 | ok | 2023.67 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.68 s |
| queue | · asr.queue_wait | 1 | ok | 2023.68 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.69 s |
| queue | · asr.queue_wait | 1 | ok | 2023.68 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.69 s |
| queue | · asr.queue_wait | 1 | ok | 2023.69 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.69 s |
| queue | · asr.queue_wait | 1 | ok | 2023.69 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.70 s |
| queue | · asr.queue_wait | 1 | ok | 2023.70 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.70 s |
| queue | · asr.queue_wait | 1 | ok | 2023.70 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.71 s |
| queue | · asr.queue_wait | 1 | ok | 2023.70 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.71 s |
| queue | · asr.queue_wait | 1 | ok | 2023.71 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.72 s |
| queue | · asr.queue_wait | 1 | ok | 2023.72 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.72 s |
| queue | · asr.queue_wait | 1 | ok | 2023.72 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.02 s | — | +2023.73 s |
| queue | · asr.queue_wait | 1 | ok | 2023.72 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.75 s |
| queue | · asr.queue_wait | 1 | ok | 2023.75 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.76 s |
| queue | · asr.queue_wait | 1 | ok | 2023.75 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +2023.76 s |
| queue | · asr.queue_wait | 1 | ok | 2023.76 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 1.07 s | 0.1 % | +2024.84 s |
| other | notes.generate | 1 | ok | 14.59 s | — | +2025.91 s |
| llm_call | · llm.note_write | 1 | ok | 14.44 s | 0.7 % | +2026.00 s |

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
| lid.recording | 90.00 s | 5.54 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 5.79 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 5.77 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 5.62 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 5.35 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 5.59 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 6.07 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 5.74 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 5.58 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.76 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 5.76 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 5.84 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.66 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 6.16 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.97 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 5.95 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.97 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.57 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 6.26 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.98 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 6.20 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 5.63 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.94 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 6.36 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 6.08 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.71 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 6.17 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 6.56 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 6.57 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 5.92 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 6.73 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 6.22 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 5.83 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 10.74 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 17.36 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 23.60 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 16.06 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 11.42 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 10.49 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 10.17 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 8.66 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 9.14 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 8.43 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 9.14 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 10.33 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 9.31 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 9.02 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 8.71 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 8.47 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 9.30 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 9.03 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 9.88 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 9.22 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 9.82 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 8.99 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 9.21 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 9.28 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 9.27 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 9.40 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 8.72 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 9.31 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 10.81 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 8.93 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 9.49 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 11.71 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 8.93 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 9.63 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 9.81 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 9.09 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 8.58 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 9.18 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 9.43 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 9.30 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 9.12 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 8.78 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 9.00 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 8.63 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 10.05 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 10.09 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 16.49 s | 1.072 |
| asr.chunk | faster_whisper | 8.73 s | 14.49 s | 1.659 |
| asr.chunk | faster_whisper | 4.28 s | 12.23 s | 2.856 |
| asr.chunk | faster_whisper | 16.38 s | 16.58 s | 1.012 |
| asr.chunk | faster_whisper | 4.54 s | 12.13 s | 2.671 |
| asr.chunk | faster_whisper | 13.53 s | 15.07 s | 1.114 |
| asr.chunk | faster_whisper | 8.12 s | 15.68 s | 1.930 |
| asr.chunk | faster_whisper | 10.59 s | 16.14 s | 1.524 |
| asr.chunk | faster_whisper | 7.90 s | 14.32 s | 1.812 |
| asr.chunk | faster_whisper | 13.28 s | 17.99 s | 1.355 |
| asr.chunk | faster_whisper | 4.48 s | 13.83 s | 3.090 |
| asr.chunk | faster_whisper | 13.12 s | 16.12 s | 1.229 |
| asr.chunk | faster_whisper | 7.48 s | 13.87 s | 1.854 |
| asr.chunk | faster_whisper | 6.24 s | 13.66 s | 2.191 |
| asr.chunk | faster_whisper | 28.38 s | 21.72 s | 0.765 |
| asr.chunk | faster_whisper | 16.28 s | 18.46 s | 1.133 |
| asr.chunk | faster_whisper | 7.04 s | 12.83 s | 1.823 |
| asr.chunk | faster_whisper | 9.63 s | 14.02 s | 1.456 |
| asr.chunk | faster_whisper | 2.49 s | 10.97 s | 4.404 |
| asr.chunk | faster_whisper | 24.16 s | 21.49 s | 0.890 |
| asr.chunk | faster_whisper | 16.64 s | 16.77 s | 1.008 |
| asr.chunk | faster_whisper | 1.28 s | 10.63 s | 8.333 |
| asr.chunk | faster_whisper | 11.71 s | 14.83 s | 1.267 |
| asr.chunk | faster_whisper | 6.46 s | 14.33 s | 2.219 |
| asr.chunk | faster_whisper | 15.71 s | 16.77 s | 1.067 |
| asr.chunk | faster_whisper | 8.73 s | 15.32 s | 1.755 |
| asr.chunk | faster_whisper | 13.47 s | 16.38 s | 1.217 |
| asr.chunk | faster_whisper | 6.84 s | 16.00 s | 2.338 |
| asr.chunk | faster_whisper | 17.82 s | 20.59 s | 1.155 |
| asr.chunk | faster_whisper | 11.61 s | 16.27 s | 1.401 |
| asr.chunk | faster_whisper | 11.10 s | 16.30 s | 1.469 |
| asr.chunk | faster_whisper | 12.41 s | 16.15 s | 1.301 |
| asr.chunk | faster_whisper | 6.24 s | 12.93 s | 2.074 |
| asr.chunk | faster_whisper | 1.82 s | 10.82 s | 5.947 |
| asr.chunk | faster_whisper | 13.85 s | 15.30 s | 1.104 |
| asr.chunk | faster_whisper | 12.44 s | 14.58 s | 1.171 |
| asr.chunk | faster_whisper | 10.84 s | 14.50 s | 1.337 |
| asr.chunk | faster_whisper | 8.96 s | 14.25 s | 1.591 |
| asr.chunk | faster_whisper | 20.76 s | 21.07 s | 1.015 |
| asr.chunk | faster_whisper | 5.98 s | 12.61 s | 2.109 |
| asr.chunk | faster_whisper | 7.77 s | 13.41 s | 1.726 |
| asr.chunk | faster_whisper | 11.87 s | 15.44 s | 1.301 |
| asr.chunk | faster_whisper | 4.48 s | 12.07 s | 2.697 |
| asr.chunk | faster_whisper | 5.53 s | 11.82 s | 2.137 |
| asr.chunk | faster_whisper | 11.64 s | 15.88 s | 1.363 |
| asr.chunk | faster_whisper | 3.00 s | 10.54 s | 3.510 |
| asr.chunk | faster_whisper | 11.39 s | 17.86 s | 1.569 |
| asr.chunk | faster_whisper | 11.77 s | 18.96 s | 1.611 |
| asr.chunk | faster_whisper | 4.48 s | 12.84 s | 2.868 |
| asr.chunk | faster_whisper | 8.64 s | 13.90 s | 1.610 |
| asr.chunk | faster_whisper | 6.01 s | 14.44 s | 2.401 |
| asr.chunk | faster_whisper | 8.03 s | 13.21 s | 1.645 |
| asr.chunk | faster_whisper | 2.56 s | 12.19 s | 4.768 |
| asr.chunk | faster_whisper | 2.49 s | 11.77 s | 4.722 |
| asr.chunk | faster_whisper | 13.44 s | 17.20 s | 1.280 |
| asr.chunk | faster_whisper | 7.58 s | 14.11 s | 1.862 |
| asr.chunk | faster_whisper | 2.68 s | 12.85 s | 4.788 |
| asr.chunk | faster_whisper | 8.83 s | 15.51 s | 1.757 |
| asr.chunk | faster_whisper | 14.14 s | 15.81 s | 1.118 |
| asr.chunk | faster_whisper | 8.25 s | 12.86 s | 1.559 |
| asr.chunk | faster_whisper | 17.34 s | 16.89 s | 0.974 |
| asr.chunk | faster_whisper | 6.24 s | 14.06 s | 2.254 |
| asr.chunk | faster_whisper | 13.85 s | 16.97 s | 1.225 |
| asr.chunk | faster_whisper | 6.97 s | 13.75 s | 1.972 |
| asr.chunk | faster_whisper | 8.48 s | 14.60 s | 1.723 |
| asr.chunk | faster_whisper | 15.45 s | 16.50 s | 1.068 |
| asr.chunk | faster_whisper | 5.88 s | 12.87 s | 2.188 |
| asr.chunk | faster_whisper | 7.20 s | 12.88 s | 1.790 |
| asr.chunk | faster_whisper | 8.09 s | 13.06 s | 1.614 |
| asr.chunk | faster_whisper | 11.80 s | 14.50 s | 1.228 |
| asr.chunk | faster_whisper | 7.48 s | 13.74 s | 1.836 |
| asr.chunk | faster_whisper | 9.18 s | 15.64 s | 1.703 |
| asr.chunk | faster_whisper | 12.06 s | 17.12 s | 1.420 |
| asr.chunk | faster_whisper | 6.33 s | 13.16 s | 2.078 |
| asr.chunk | faster_whisper | 9.63 s | 15.13 s | 1.572 |
| asr.chunk | faster_whisper | 10.81 s | 15.16 s | 1.402 |
| asr.chunk | faster_whisper | 30.00 s | 30.13 s | 1.004 |
| asr.chunk | faster_whisper | 4.24 s | 11.51 s | 2.718 |
| asr.chunk | faster_whisper | 5.12 s | 13.27 s | 2.594 |
| asr.chunk | faster_whisper | 6.91 s | 13.31 s | 1.926 |
| asr.chunk | faster_whisper | 1.76 s | 12.02 s | 6.844 |
| asr.chunk | faster_whisper | 1.98 s | 11.17 s | 5.639 |

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
| load | ok | 3.71 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 101.50 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.07 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 14.44 s | 4,887 | 0 | 0 | 1,130 | — (not_supported) |
| **total** |  | 2 |  |  | 15.50 s | 4,899 | 0 | 0 | 1,136 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,571,904 B (2.29 GiB) → 2,423,492,608 B (2.26 GiB) |
| swap used | 1,428,201,472 B (1.33 GiB) → 1,425,784,832 B (1.33 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,610 B |

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

- Top critical-path stages: asr_primary 1225.07 s (60.0 %); language_detection 658.95 s (32.3 %); diarization_infer 101.50 s (5.0 %).
- Reprocessing ratio: 0.894.
- Cold loads: vad.model 1.45 s; diarization.load 3.71 s.
- Queue wait: 13.96 s.
- LLM latency share of wall: 0.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Hypothesis: ASR dominates (rtf 2.287, asr_primary 60.0 % of wall); consider a smaller model, quantization or a lower beam.

Checked, did not fire: `asr_device_configured`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
