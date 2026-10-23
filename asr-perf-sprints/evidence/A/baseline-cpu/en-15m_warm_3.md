# Diagnostics — recording 87c903f8-49da-464e-a912-4284d16f5200

Run `d2428f37-b681-47f7-9d50-67bae273bc84` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 87c903f8-49da-464e-a912-4284d16f5200 |
| processing_run_id | d2428f37-b681-47f7-9d50-67bae273bc84 |
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
| processing_wall_seconds | 1315.69 s |
| rtf | 1.474 |
| speedup | 0.678 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.24 s | 0.0 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 1265.40 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.53 s | 0.0 % | +0.04 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.57 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.57 s |
| vad | · vad.speech_runs | 1 | ok | 15.23 s | 1.2 % | +0.57 s |
| language_detection | · lid.recording | 1 | ok | 5.37 s | 0.4 % | +15.81 s |
| language_detection | · lid.run | 1 | ok | 5.22 s | 0.4 % | +21.18 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +26.40 s |
| language_detection | · lid.run | 1 | ok | 5.18 s | 0.4 % | +31.64 s |
| language_detection | · lid.run | 1 | ok | 5.61 s | 0.4 % | +36.82 s |
| language_detection | · lid.run | 1 | ok | 5.12 s | 0.4 % | +42.43 s |
| language_detection | · lid.run | 1 | ok | 5.14 s | 0.4 % | +47.55 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 0.4 % | +52.69 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 0.4 % | +57.78 s |
| language_detection | · lid.run | 1 | ok | 5.43 s | 0.4 % | +63.24 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +68.67 s |
| language_detection | · lid.run | 1 | ok | 5.40 s | 0.4 % | +74.24 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 0.4 % | +79.64 s |
| language_detection | · lid.run | 1 | ok | 6.37 s | 0.5 % | +85.10 s |
| language_detection | · lid.run | 1 | ok | 5.54 s | 0.4 % | +91.48 s |
| language_detection | · lid.run | 1 | ok | 6.20 s | 0.5 % | +97.03 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 0.4 % | +103.23 s |
| language_detection | · lid.run | 1 | ok | 5.80 s | 0.4 % | +108.76 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 0.4 % | +114.57 s |
| language_detection | · lid.run | 1 | ok | 6.11 s | 0.5 % | +120.38 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +126.49 s |
| language_detection | · lid.run | 1 | ok | 6.05 s | 0.5 % | +132.12 s |
| language_detection | · lid.run | 1 | ok | 6.32 s | 0.5 % | +138.19 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.5 % | +144.52 s |
| language_detection | · lid.run | 1 | ok | 6.49 s | 0.5 % | +150.46 s |
| language_detection | · lid.run | 1 | ok | 6.30 s | 0.5 % | +156.95 s |
| language_detection | · lid.run | 1 | ok | 6.33 s | 0.5 % | +163.26 s |
| language_detection | · lid.run | 1 | ok | 5.90 s | 0.4 % | +169.59 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.5 % | +175.50 s |
| language_detection | · lid.run | 1 | ok | 6.27 s | 0.5 % | +181.44 s |
| language_detection | · lid.run | 1 | ok | 6.02 s | 0.5 % | +187.71 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +193.73 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 0.5 % | +199.41 s |
| language_detection | · lid.run | 1 | ok | 6.60 s | 0.5 % | +205.44 s |
| language_detection | · lid.run | 1 | ok | 6.28 s | 0.5 % | +212.05 s |
| language_detection | · lid.run | 1 | ok | 6.26 s | 0.5 % | +218.33 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +224.60 s |
| language_detection | · lid.run | 1 | ok | 6.17 s | 0.5 % | +230.27 s |
| language_detection | · lid.run | 1 | ok | 6.10 s | 0.5 % | +236.45 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.5 % | +242.55 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 0.5 % | +248.49 s |
| language_detection | · lid.run | 1 | ok | 5.75 s | 0.4 % | +254.52 s |
| language_detection | · lid.run | 1 | ok | 5.99 s | 0.5 % | +260.28 s |
| language_detection | · lid.run | 1 | ok | 6.33 s | 0.5 % | +266.28 s |
| language_detection | · lid.run | 1 | ok | 5.96 s | 0.5 % | +272.61 s |
| language_detection | · lid.run | 1 | ok | 6.26 s | 0.5 % | +278.58 s |
| language_detection | · lid.run | 1 | ok | 5.73 s | 0.4 % | +284.85 s |
| language_detection | · lid.run | 1 | ok | 5.96 s | 0.5 % | +290.58 s |
| language_detection | · lid.run | 1 | ok | 5.92 s | 0.5 % | +296.54 s |
| language_detection | · lid.run | 1 | ok | 6.18 s | 0.5 % | +302.47 s |
| language_detection | · lid.run | 1 | ok | 6.29 s | 0.5 % | +308.66 s |
| language_detection | · lid.run | 1 | ok | 6.08 s | 0.5 % | +314.95 s |
| language_detection | · lid.run | 1 | ok | 5.95 s | 0.5 % | +321.04 s |
| language_detection | · lid.run | 1 | ok | 6.67 s | 0.5 % | +326.99 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +333.67 s |
| language_detection | · lid.run | 1 | ok | 6.00 s | 0.5 % | +339.34 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +345.34 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +350.98 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +356.49 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +362.12 s |
| language_detection | · lid.run | 1 | ok | 5.60 s | 0.4 % | +367.76 s |
| language_detection | · lid.run | 1 | ok | 5.65 s | 0.4 % | +373.36 s |
| language_detection | · lid.run | 1 | ok | 5.84 s | 0.4 % | +379.01 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 0.4 % | +384.86 s |
| language_detection | · lid.run | 1 | ok | 6.14 s | 0.5 % | +390.45 s |
| language_detection | · lid.run | 1 | ok | 5.95 s | 0.5 % | +396.60 s |
| language_detection | · lid.run | 1 | ok | 5.75 s | 0.4 % | +402.55 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.5 % | +408.30 s |
| language_detection | · lid.run | 1 | ok | 5.54 s | 0.4 % | +414.25 s |
| language_detection | · lid.run | 1 | ok | 6.09 s | 0.5 % | +419.78 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +425.88 s |
| language_detection | · lid.run | 1 | ok | 5.96 s | 0.5 % | +431.50 s |
| language_detection | · lid.run | 1 | ok | 5.64 s | 0.4 % | +437.46 s |
| language_detection | · lid.run | 1 | ok | 5.64 s | 0.4 % | +443.11 s |
| language_detection | · lid.run | 1 | ok | 6.48 s | 0.5 % | +448.75 s |
| language_detection | · lid.run | 1 | ok | 5.76 s | 0.4 % | +455.24 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +461.00 s |
| language_detection | · lid.run | 1 | ok | 5.68 s | 0.4 % | +466.56 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +472.24 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 733.57 s | 55.8 % | +477.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.05 s | 0.8 % | +477.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.48 s | 0.6 % | +487.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.95 s | 0.6 % | +496.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.11 s | 0.8 % | +504.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.93 s | 0.6 % | +514.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.37 s | 0.7 % | +522.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.29 s | 0.6 % | +531.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.98 s | 0.7 % | +540.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.88 s | 0.7 % | +549.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.98 s | 0.8 % | +557.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.78 s | 0.7 % | +567.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.04 s | 0.8 % | +576.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.66 s | 0.7 % | +586.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.46 s | 0.6 % | +595.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.91 s | 1.0 % | +603.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.04 s | 0.8 % | +616.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.74 s | 0.6 % | +627.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.99 s | 0.7 % | +635.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.07 s | 0.5 % | +644.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.02 s | 1.0 % | +651.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.50 s | 0.8 % | +664.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.79 s | 0.5 % | +675.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.07 s | 0.7 % | +681.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.06 s | 0.7 % | +691.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.38 s | 0.8 % | +700.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.40 s | 0.7 % | +710.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 0.8 % | +719.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.24 s | 0.6 % | +729.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.67 s | 0.8 % | +738.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.61 s | 0.7 % | +748.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.63 s | 0.7 % | +758.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.14 s | 0.8 % | +767.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.84 s | 0.7 % | +778.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.96 s | 0.5 % | +786.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.58 s | 0.7 % | +793.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.51 s | 0.7 % | +803.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.54 s | 0.8 % | +813.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.14 s | 0.6 % | +823.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.58 s | 1.0 % | +831.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 0.6 % | +844.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.30 s | 0.6 % | +852.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.19 s | 0.8 % | +860.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.02 s | 0.6 % | +870.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.29 s | 0.6 % | +878.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.81 s | 0.7 % | +887.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.35 s | 0.6 % | +897.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.65 s | 0.8 % | +904.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 0.7 % | +915.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.60 s | 0.7 % | +924.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.74 s | 0.7 % | +933.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.69 s | 0.6 % | +943.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.94 s | 0.6 % | +950.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.69 s | 0.6 % | +958.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.96 s | 0.5 % | +966.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.51 s | 0.7 % | +973.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.82 s | 0.6 % | +982.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.73 s | 0.5 % | +990.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 0.7 % | +997.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.27 s | 0.7 % | +1006.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.89 s | 0.6 % | +1015.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.25 s | 0.8 % | +1023.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.28 s | 0.6 % | +1033.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.47 s | 0.7 % | +1041.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.26 s | 0.6 % | +1050.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.31 s | 0.6 % | +1058.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.62 s | 0.7 % | +1067.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.81 s | 0.6 % | +1076.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.61 s | 0.6 % | +1084.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.84 s | 0.6 % | +1092.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.91 s | 0.7 % | +1100.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.47 s | 0.6 % | +1108.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.27 s | 0.6 % | +1117.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.15 s | 0.7 % | +1125.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.95 s | 0.6 % | +1134.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.08 s | 0.7 % | +1142.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.61 s | 0.7 % | +1151.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.72 s | 1.2 % | +1160.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.15 s | 0.5 % | +1176.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.47 s | 0.6 % | +1183.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.60 s | 0.6 % | +1190.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.30 s | 0.5 % | +1198.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.64 s | 0.5 % | +1204.75 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +1211.39 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1211.41 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1211.51 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +1211.51 s |
| diarization_infer | · diarization.infer | 1 | ok | 53.73 s | 4.1 % | +1211.51 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.17 s | 0.0 % | +1265.24 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1265.41 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +1265.42 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.45 s |
| queue | · asr.queue_wait | 1 | ok | 1265.45 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.45 s |
| queue | · asr.queue_wait | 1 | ok | 1265.45 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.46 s |
| queue | · asr.queue_wait | 1 | ok | 1265.45 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.46 s |
| queue | · asr.queue_wait | 1 | ok | 1265.45 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.46 s |
| queue | · asr.queue_wait | 1 | ok | 1265.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.46 s |
| queue | · asr.queue_wait | 1 | ok | 1265.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.47 s |
| queue | · asr.queue_wait | 1 | ok | 1265.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.47 s |
| queue | · asr.queue_wait | 1 | ok | 1265.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.47 s |
| queue | · asr.queue_wait | 1 | ok | 1265.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.47 s |
| queue | · asr.queue_wait | 1 | ok | 1265.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.48 s |
| queue | · asr.queue_wait | 1 | ok | 1265.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.48 s |
| queue | · asr.queue_wait | 1 | ok | 1265.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.48 s |
| queue | · asr.queue_wait | 1 | ok | 1265.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.49 s |
| queue | · asr.queue_wait | 1 | ok | 1265.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.49 s |
| queue | · asr.queue_wait | 1 | ok | 1265.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.49 s |
| queue | · asr.queue_wait | 1 | ok | 1265.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.49 s |
| queue | · asr.queue_wait | 1 | ok | 1265.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.50 s |
| queue | · asr.queue_wait | 1 | ok | 1265.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.50 s |
| queue | · asr.queue_wait | 1 | ok | 1265.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1265.50 s |
| queue | · asr.queue_wait | 1 | ok | 1265.50 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.53 s | 0.0 % | +1266.33 s |
| other | notes.generate | 1 | ok | 48.83 s | — | +1266.86 s |
| llm_call | · llm.note_write | 1 | ok | 48.73 s | 3.7 % | +1266.92 s |

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
| lid.recording | 90.00 s | 5.37 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 5.22 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 5.23 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 5.18 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 5.61 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 5.12 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 5.14 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 5.09 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 5.46 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.43 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 5.56 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 5.40 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.46 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 6.37 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.54 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 6.20 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.53 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.80 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.81 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 6.11 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.63 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 6.05 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 6.32 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 5.94 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 6.49 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 6.30 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 6.33 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 5.90 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 5.94 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 6.27 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 6.02 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 5.67 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 6.03 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 6.60 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 6.28 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 6.26 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.67 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 6.17 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 6.10 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.94 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 6.03 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 5.75 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 5.99 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 6.33 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 5.96 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 6.26 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.73 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.96 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 5.92 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 6.18 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 6.29 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 6.08 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 5.95 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 6.67 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 5.67 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 6.00 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 5.63 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 5.51 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 5.63 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.63 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 5.60 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 5.65 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 5.84 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 5.59 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 6.14 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 5.95 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 5.75 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 5.94 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 5.54 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 6.09 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 5.62 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 5.96 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 5.64 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 5.64 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 6.48 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 5.76 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.56 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 5.68 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 5.57 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 10.05 s | 0.653 |
| asr.chunk | faster_whisper | 8.73 s | 8.48 s | 0.971 |
| asr.chunk | faster_whisper | 4.28 s | 7.95 s | 1.855 |
| asr.chunk | faster_whisper | 16.38 s | 10.11 s | 0.617 |
| asr.chunk | faster_whisper | 4.54 s | 7.93 s | 1.748 |
| asr.chunk | faster_whisper | 13.53 s | 9.37 s | 0.693 |
| asr.chunk | faster_whisper | 8.12 s | 8.29 s | 1.020 |
| asr.chunk | faster_whisper | 10.59 s | 8.98 s | 0.848 |
| asr.chunk | faster_whisper | 7.90 s | 8.88 s | 1.124 |
| asr.chunk | faster_whisper | 13.28 s | 9.98 s | 0.752 |
| asr.chunk | faster_whisper | 4.48 s | 8.78 s | 1.962 |
| asr.chunk | faster_whisper | 13.12 s | 10.04 s | 0.765 |
| asr.chunk | faster_whisper | 7.48 s | 8.66 s | 1.157 |
| asr.chunk | faster_whisper | 6.24 s | 8.46 s | 1.357 |
| asr.chunk | faster_whisper | 28.38 s | 12.91 s | 0.455 |
| asr.chunk | faster_whisper | 16.28 s | 11.04 s | 0.678 |
| asr.chunk | faster_whisper | 7.04 s | 7.74 s | 1.099 |
| asr.chunk | faster_whisper | 9.63 s | 8.99 s | 0.934 |
| asr.chunk | faster_whisper | 2.49 s | 7.07 s | 2.836 |
| asr.chunk | faster_whisper | 24.16 s | 13.02 s | 0.539 |
| asr.chunk | faster_whisper | 16.64 s | 10.50 s | 0.631 |
| asr.chunk | faster_whisper | 1.28 s | 6.79 s | 5.321 |
| asr.chunk | faster_whisper | 11.71 s | 9.07 s | 0.775 |
| asr.chunk | faster_whisper | 6.46 s | 9.06 s | 1.402 |
| asr.chunk | faster_whisper | 15.71 s | 10.38 s | 0.661 |
| asr.chunk | faster_whisper | 8.73 s | 9.40 s | 1.077 |
| asr.chunk | faster_whisper | 13.47 s | 9.89 s | 0.735 |
| asr.chunk | faster_whisper | 6.84 s | 8.24 s | 1.204 |
| asr.chunk | faster_whisper | 17.82 s | 10.67 s | 0.599 |
| asr.chunk | faster_whisper | 11.61 s | 9.61 s | 0.827 |
| asr.chunk | faster_whisper | 11.10 s | 9.63 s | 0.868 |
| asr.chunk | faster_whisper | 12.41 s | 10.14 s | 0.817 |
| asr.chunk | faster_whisper | 6.24 s | 8.84 s | 1.417 |
| asr.chunk | faster_whisper | 1.82 s | 6.96 s | 3.823 |
| asr.chunk | faster_whisper | 13.85 s | 9.58 s | 0.692 |
| asr.chunk | faster_whisper | 12.44 s | 9.51 s | 0.764 |
| asr.chunk | faster_whisper | 10.84 s | 10.53 s | 0.971 |
| asr.chunk | faster_whisper | 8.96 s | 8.14 s | 0.909 |
| asr.chunk | faster_whisper | 20.76 s | 12.58 s | 0.606 |
| asr.chunk | faster_whisper | 5.98 s | 8.08 s | 1.351 |
| asr.chunk | faster_whisper | 7.77 s | 8.30 s | 1.068 |
| asr.chunk | faster_whisper | 11.87 s | 10.19 s | 0.859 |
| asr.chunk | faster_whisper | 4.48 s | 8.02 s | 1.792 |
| asr.chunk | faster_whisper | 5.53 s | 8.29 s | 1.498 |
| asr.chunk | faster_whisper | 11.64 s | 9.81 s | 0.842 |
| asr.chunk | faster_whisper | 3.00 s | 7.35 s | 2.447 |
| asr.chunk | faster_whisper | 11.39 s | 10.64 s | 0.935 |
| asr.chunk | faster_whisper | 11.77 s | 9.68 s | 0.822 |
| asr.chunk | faster_whisper | 4.48 s | 8.60 s | 1.921 |
| asr.chunk | faster_whisper | 8.64 s | 9.74 s | 1.127 |
| asr.chunk | faster_whisper | 6.01 s | 7.69 s | 1.279 |
| asr.chunk | faster_whisper | 8.03 s | 7.94 s | 0.989 |
| asr.chunk | faster_whisper | 2.56 s | 7.69 s | 3.008 |
| asr.chunk | faster_whisper | 2.49 s | 6.96 s | 2.793 |
| asr.chunk | faster_whisper | 13.44 s | 9.51 s | 0.708 |
| asr.chunk | faster_whisper | 7.58 s | 7.82 s | 1.031 |
| asr.chunk | faster_whisper | 2.68 s | 6.73 s | 2.508 |
| asr.chunk | faster_whisper | 8.83 s | 8.96 s | 1.015 |
| asr.chunk | faster_whisper | 14.14 s | 9.27 s | 0.656 |
| asr.chunk | faster_whisper | 8.25 s | 7.89 s | 0.956 |
| asr.chunk | faster_whisper | 17.34 s | 10.25 s | 0.591 |
| asr.chunk | faster_whisper | 6.24 s | 7.28 s | 1.168 |
| asr.chunk | faster_whisper | 13.85 s | 9.47 s | 0.684 |
| asr.chunk | faster_whisper | 6.97 s | 8.26 s | 1.184 |
| asr.chunk | faster_whisper | 8.48 s | 8.31 s | 0.981 |
| asr.chunk | faster_whisper | 15.45 s | 9.62 s | 0.623 |
| asr.chunk | faster_whisper | 5.88 s | 7.81 s | 1.327 |
| asr.chunk | faster_whisper | 7.20 s | 7.61 s | 1.058 |
| asr.chunk | faster_whisper | 8.09 s | 7.84 s | 0.969 |
| asr.chunk | faster_whisper | 11.80 s | 8.91 s | 0.755 |
| asr.chunk | faster_whisper | 7.48 s | 8.47 s | 1.132 |
| asr.chunk | faster_whisper | 9.18 s | 8.27 s | 0.901 |
| asr.chunk | faster_whisper | 12.06 s | 9.15 s | 0.759 |
| asr.chunk | faster_whisper | 6.33 s | 7.94 s | 1.255 |
| asr.chunk | faster_whisper | 9.63 s | 9.08 s | 0.943 |
| asr.chunk | faster_whisper | 10.81 s | 8.61 s | 0.796 |
| asr.chunk | faster_whisper | 30.00 s | 15.72 s | 0.524 |
| asr.chunk | faster_whisper | 4.24 s | 7.15 s | 1.687 |
| asr.chunk | faster_whisper | 5.12 s | 7.47 s | 1.459 |
| asr.chunk | faster_whisper | 6.91 s | 7.60 s | 1.100 |
| asr.chunk | faster_whisper | 1.76 s | 6.30 s | 3.588 |
| asr.chunk | faster_whisper | 1.98 s | 6.64 s | 3.353 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 53.73 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.53 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 48.73 s | 4,887 | 0 | 0 | 937 | — (not_supported) |
| **total** |  | 2 |  |  | 49.26 s | 4,899 | 0 | 0 | 943 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,392,592,384 B (2.23 GiB) → 2,409,623,552 B (2.24 GiB) |
| swap used | 329,834,496 B (0.31 GiB) → 389,783,552 B (0.36 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 2,026 B |

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

- Top critical-path stages: asr_primary 733.57 s (55.8 %); language_detection 461.70 s (35.1 %); diarization_infer 53.73 s (4.1 %).
- Reprocessing ratio: 0.894.
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: 3.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
