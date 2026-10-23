# Diagnostics — recording f2cdc915-338f-4760-b7c6-ed921df5a4cd

Run `04d32871-0077-4300-85b2-c694e751aba8` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | f2cdc915-338f-4760-b7c6-ed921df5a4cd |
| processing_run_id | 04d32871-0077-4300-85b2-c694e751aba8 |
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
| processing_wall_seconds | 1249.26 s |
| rtf | 1.400 |
| speedup | 0.714 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.20 s | 0.0 % | -0.20 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.14 s |
| other | worker_job | 1 | ok | 1235.86 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.00 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.42 s | 0.0 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.43 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.43 s |
| vad | · vad.speech_runs | 1 | ok | 15.32 s | 1.2 % | +0.43 s |
| language_detection | · lid.recording | 1 | ok | 5.67 s | 0.5 % | +15.76 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 0.4 % | +21.44 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 0.4 % | +26.50 s |
| language_detection | · lid.run | 1 | ok | 5.11 s | 0.4 % | +31.54 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 0.4 % | +36.65 s |
| language_detection | · lid.run | 1 | ok | 5.12 s | 0.4 % | +41.63 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 0.5 % | +46.76 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 0.4 % | +52.73 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.5 % | +58.03 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 0.4 % | +63.80 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 0.4 % | +68.90 s |
| language_detection | · lid.run | 1 | ok | 5.43 s | 0.4 % | +73.99 s |
| language_detection | · lid.run | 1 | ok | 5.64 s | 0.5 % | +79.43 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +85.07 s |
| language_detection | · lid.run | 1 | ok | 5.45 s | 0.4 % | +90.32 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 0.4 % | +95.77 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 0.4 % | +101.16 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +106.52 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 0.4 % | +112.09 s |
| language_detection | · lid.run | 1 | ok | 5.71 s | 0.5 % | +117.68 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +123.39 s |
| language_detection | · lid.run | 1 | ok | 5.49 s | 0.4 % | +128.91 s |
| language_detection | · lid.run | 1 | ok | 5.45 s | 0.4 % | +134.40 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 0.4 % | +139.86 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 0.4 % | +145.36 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +150.82 s |
| language_detection | · lid.run | 1 | ok | 6.24 s | 0.5 % | +156.39 s |
| language_detection | · lid.run | 1 | ok | 5.90 s | 0.5 % | +162.64 s |
| language_detection | · lid.run | 1 | ok | 6.29 s | 0.5 % | +168.54 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +174.83 s |
| language_detection | · lid.run | 1 | ok | 5.70 s | 0.5 % | +180.35 s |
| language_detection | · lid.run | 1 | ok | 5.61 s | 0.4 % | +186.05 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +191.66 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +197.14 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 0.5 % | +202.70 s |
| language_detection | · lid.run | 1 | ok | 5.65 s | 0.5 % | +208.39 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.5 % | +214.04 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.5 % | +219.70 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +225.36 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 0.4 % | +230.92 s |
| language_detection | · lid.run | 1 | ok | 5.44 s | 0.4 % | +236.47 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 0.5 % | +241.91 s |
| language_detection | · lid.run | 1 | ok | 6.58 s | 0.5 % | +247.69 s |
| language_detection | · lid.run | 1 | ok | 5.49 s | 0.4 % | +254.28 s |
| language_detection | · lid.run | 1 | ok | 5.75 s | 0.5 % | +259.77 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.5 % | +265.52 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.5 % | +271.19 s |
| language_detection | · lid.run | 1 | ok | 5.41 s | 0.4 % | +276.87 s |
| language_detection | · lid.run | 1 | ok | 6.00 s | 0.5 % | +282.28 s |
| language_detection | · lid.run | 1 | ok | 6.08 s | 0.5 % | +288.28 s |
| language_detection | · lid.run | 1 | ok | 5.70 s | 0.5 % | +294.36 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 0.4 % | +300.06 s |
| language_detection | · lid.run | 1 | ok | 5.71 s | 0.5 % | +305.57 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +311.28 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +316.75 s |
| language_detection | · lid.run | 1 | ok | 5.40 s | 0.4 % | +322.28 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +327.68 s |
| language_detection | · lid.run | 1 | ok | 5.61 s | 0.4 % | +333.24 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +338.85 s |
| language_detection | · lid.run | 1 | ok | 5.37 s | 0.4 % | +344.42 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +349.79 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +355.30 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +360.87 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +366.40 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +371.91 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +377.53 s |
| language_detection | · lid.run | 1 | ok | 5.41 s | 0.4 % | +383.09 s |
| language_detection | · lid.run | 1 | ok | 5.68 s | 0.5 % | +388.51 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 0.4 % | +394.19 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.4 % | +399.78 s |
| language_detection | · lid.run | 1 | ok | 5.43 s | 0.4 % | +405.37 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 0.5 % | +410.80 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +416.87 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.5 % | +422.50 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +428.16 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 0.4 % | +433.65 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +439.04 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 0.4 % | +444.55 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +450.09 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 725.14 s | 58.0 % | +455.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.95 s | 0.8 % | +455.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.64 s | 0.7 % | +465.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.46 s | 0.6 % | +474.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.58 s | 0.8 % | +481.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.15 s | 0.6 % | +491.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 0.7 % | +498.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.44 s | 0.7 % | +507.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.00 s | 0.7 % | +515.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 0.6 % | +524.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.85 s | 0.8 % | +532.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.63 s | 0.6 % | +542.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 0.7 % | +550.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 0.7 % | +559.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.71 s | 0.6 % | +567.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.99 s | 1.0 % | +575.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.53 s | 0.8 % | +588.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.70 s | 0.6 % | +598.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.77 s | 0.7 % | +606.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.54 s | 0.5 % | +615.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.66 s | 1.0 % | +621.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.43 s | 0.8 % | +634.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.38 s | 0.5 % | +644.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.99 s | 0.7 % | +651.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.67 s | 0.6 % | +660.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.08 s | 0.8 % | +667.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.74 s | 0.7 % | +677.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.07 s | 0.7 % | +686.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.57 s | 0.7 % | +695.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.95 s | 0.8 % | +704.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.54 s | 0.8 % | +714.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.97 s | 0.8 % | +723.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.88 s | 0.8 % | +733.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.22 s | 0.7 % | +743.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.79 s | 0.5 % | +751.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.17 s | 0.8 % | +758.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.17 s | 0.9 % | +768.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.04 s | 0.8 % | +779.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.97 s | 0.7 % | +789.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.41 s | 1.0 % | +798.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.86 s | 0.6 % | +811.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.31 s | 0.7 % | +819.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.31 s | 0.7 % | +827.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.39 s | 0.6 % | +836.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.25 s | 0.6 % | +844.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.32 s | 0.7 % | +851.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.77 s | 0.5 % | +860.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.79 s | 0.7 % | +867.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.28 s | 0.7 % | +876.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.43 s | 0.6 % | +885.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.91 s | 0.7 % | +893.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.81 s | 0.6 % | +901.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.05 s | 0.6 % | +909.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.38 s | 0.6 % | +917.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.77 s | 0.6 % | +925.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.16 s | 0.8 % | +933.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.88 s | 0.6 % | +943.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.80 s | 0.5 % | +951.06 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.18 s | 0.7 % | +957.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.77 s | 0.8 % | +967.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.91 s | 0.6 % | +976.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.50 s | 0.8 % | +984.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.91 s | 0.6 % | +995.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.85 s | 0.8 % | +1003.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.56 s | 0.8 % | +1013.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.68 s | 0.7 % | +1022.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.84 s | 0.8 % | +1031.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.82 s | 0.7 % | +1041.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.14 s | 0.7 % | +1049.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.02 s | 0.6 % | +1058.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.15 s | 0.7 % | +1066.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.66 s | 0.7 % | +1075.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.62 s | 0.7 % | +1083.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.66 s | 0.8 % | +1092.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.83 s | 0.6 % | +1102.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.24 s | 0.7 % | +1110.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.85 s | 0.7 % | +1119.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.91 s | 1.4 % | +1128.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.97 s | 0.6 % | +1145.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.61 s | 0.6 % | +1152.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.74 s | 0.6 % | +1159.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.43 s | 0.5 % | +1167.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.89 s | 0.6 % | +1173.83 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +1180.72 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1180.74 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1180.84 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +1180.84 s |
| diarization_infer | · diarization.infer | 1 | ok | 54.81 s | 4.4 % | +1180.84 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.18 s | 0.0 % | +1235.65 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1235.83 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +1235.83 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.89 s |
| queue | · asr.queue_wait | 1 | ok | 1235.89 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.89 s |
| queue | · asr.queue_wait | 1 | ok | 1235.89 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.89 s |
| queue | · asr.queue_wait | 1 | ok | 1235.89 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.90 s |
| queue | · asr.queue_wait | 1 | ok | 1235.90 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.90 s |
| queue | · asr.queue_wait | 1 | ok | 1235.90 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.90 s |
| queue | · asr.queue_wait | 1 | ok | 1235.90 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.91 s |
| queue | · asr.queue_wait | 1 | ok | 1235.90 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.91 s |
| queue | · asr.queue_wait | 1 | ok | 1235.91 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.91 s |
| queue | · asr.queue_wait | 1 | ok | 1235.91 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.91 s |
| queue | · asr.queue_wait | 1 | ok | 1235.91 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.92 s |
| queue | · asr.queue_wait | 1 | ok | 1235.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.92 s |
| queue | · asr.queue_wait | 1 | ok | 1235.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.92 s |
| queue | · asr.queue_wait | 1 | ok | 1235.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.92 s |
| queue | · asr.queue_wait | 1 | ok | 1235.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.93 s |
| queue | · asr.queue_wait | 1 | ok | 1235.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.93 s |
| queue | · asr.queue_wait | 1 | ok | 1235.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.93 s |
| queue | · asr.queue_wait | 1 | ok | 1235.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.94 s |
| queue | · asr.queue_wait | 1 | ok | 1235.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.94 s |
| queue | · asr.queue_wait | 1 | ok | 1235.94 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1235.94 s |
| queue | · asr.queue_wait | 1 | ok | 1235.94 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.60 s | 0.0 % | +1237.68 s |
| other | notes.generate | 1 | ok | 10.97 s | — | +1238.29 s |
| llm_call | · llm.note_write | 1 | ok | 10.88 s | 0.9 % | +1238.34 s |

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
| lid.recording | 90.00 s | 5.67 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 5.06 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 5.03 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 5.11 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 4.98 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 5.12 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 5.97 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 5.29 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 5.77 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.09 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 5.10 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 5.43 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.64 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 5.25 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.45 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 5.39 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.36 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.56 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.59 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.71 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.52 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 5.49 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.45 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 5.50 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 5.46 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.57 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 6.24 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 5.90 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 6.29 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 5.52 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 5.70 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 5.61 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 5.48 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 5.56 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 5.69 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 5.65 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.66 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 5.66 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 5.56 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.55 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 5.44 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 5.78 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 6.58 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 5.49 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 5.75 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 5.67 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.67 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.41 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 6.00 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 6.08 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 5.70 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 5.50 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 5.71 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 5.47 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 5.52 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 5.40 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 5.56 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 5.61 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 5.56 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.37 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 5.51 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 5.57 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 5.52 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 5.51 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 5.62 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 5.56 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 5.41 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 5.68 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 5.59 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 5.58 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 5.43 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 6.07 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 5.62 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 5.67 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 5.48 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 5.39 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.51 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 5.53 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 5.48 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 9.95 s | 0.646 |
| asr.chunk | faster_whisper | 8.73 s | 8.64 s | 0.989 |
| asr.chunk | faster_whisper | 4.28 s | 7.46 s | 1.740 |
| asr.chunk | faster_whisper | 16.38 s | 9.58 s | 0.585 |
| asr.chunk | faster_whisper | 4.54 s | 7.15 s | 1.574 |
| asr.chunk | faster_whisper | 13.53 s | 8.89 s | 0.657 |
| asr.chunk | faster_whisper | 8.12 s | 8.44 s | 1.039 |
| asr.chunk | faster_whisper | 10.59 s | 9.00 s | 0.850 |
| asr.chunk | faster_whisper | 7.90 s | 8.08 s | 1.022 |
| asr.chunk | faster_whisper | 13.28 s | 9.85 s | 0.742 |
| asr.chunk | faster_whisper | 4.48 s | 7.63 s | 1.706 |
| asr.chunk | faster_whisper | 13.12 s | 8.89 s | 0.678 |
| asr.chunk | faster_whisper | 7.48 s | 8.16 s | 1.090 |
| asr.chunk | faster_whisper | 6.24 s | 7.71 s | 1.236 |
| asr.chunk | faster_whisper | 28.38 s | 12.99 s | 0.458 |
| asr.chunk | faster_whisper | 16.28 s | 10.53 s | 0.647 |
| asr.chunk | faster_whisper | 7.04 s | 7.70 s | 1.094 |
| asr.chunk | faster_whisper | 9.63 s | 8.77 s | 0.911 |
| asr.chunk | faster_whisper | 2.49 s | 6.54 s | 2.623 |
| asr.chunk | faster_whisper | 24.16 s | 12.66 s | 0.524 |
| asr.chunk | faster_whisper | 16.64 s | 10.43 s | 0.627 |
| asr.chunk | faster_whisper | 1.28 s | 6.38 s | 4.999 |
| asr.chunk | faster_whisper | 11.71 s | 8.99 s | 0.768 |
| asr.chunk | faster_whisper | 6.46 s | 7.67 s | 1.188 |
| asr.chunk | faster_whisper | 15.71 s | 10.08 s | 0.642 |
| asr.chunk | faster_whisper | 8.73 s | 8.74 s | 1.001 |
| asr.chunk | faster_whisper | 13.47 s | 9.07 s | 0.673 |
| asr.chunk | faster_whisper | 6.84 s | 8.57 s | 1.252 |
| asr.chunk | faster_whisper | 17.82 s | 9.95 s | 0.559 |
| asr.chunk | faster_whisper | 11.61 s | 9.54 s | 0.822 |
| asr.chunk | faster_whisper | 11.10 s | 9.97 s | 0.898 |
| asr.chunk | faster_whisper | 12.41 s | 9.87 s | 0.796 |
| asr.chunk | faster_whisper | 6.24 s | 8.22 s | 1.318 |
| asr.chunk | faster_whisper | 1.82 s | 6.79 s | 3.728 |
| asr.chunk | faster_whisper | 13.85 s | 10.17 s | 0.734 |
| asr.chunk | faster_whisper | 12.44 s | 11.17 s | 0.897 |
| asr.chunk | faster_whisper | 10.84 s | 10.04 s | 0.926 |
| asr.chunk | faster_whisper | 8.96 s | 8.97 s | 1.001 |
| asr.chunk | faster_whisper | 20.76 s | 12.41 s | 0.598 |
| asr.chunk | faster_whisper | 5.98 s | 7.86 s | 1.315 |
| asr.chunk | faster_whisper | 7.77 s | 8.31 s | 1.070 |
| asr.chunk | faster_whisper | 11.87 s | 9.31 s | 0.784 |
| asr.chunk | faster_whisper | 4.48 s | 7.39 s | 1.651 |
| asr.chunk | faster_whisper | 5.53 s | 7.25 s | 1.310 |
| asr.chunk | faster_whisper | 11.64 s | 9.32 s | 0.800 |
| asr.chunk | faster_whisper | 3.00 s | 6.77 s | 2.254 |
| asr.chunk | faster_whisper | 11.39 s | 8.79 s | 0.771 |
| asr.chunk | faster_whisper | 11.77 s | 9.28 s | 0.788 |
| asr.chunk | faster_whisper | 4.48 s | 7.43 s | 1.660 |
| asr.chunk | faster_whisper | 8.64 s | 8.91 s | 1.031 |
| asr.chunk | faster_whisper | 6.01 s | 7.81 s | 1.299 |
| asr.chunk | faster_whisper | 8.03 s | 8.05 s | 1.003 |
| asr.chunk | faster_whisper | 2.56 s | 7.38 s | 2.888 |
| asr.chunk | faster_whisper | 2.49 s | 7.77 s | 3.118 |
| asr.chunk | faster_whisper | 13.44 s | 10.16 s | 0.756 |
| asr.chunk | faster_whisper | 7.58 s | 7.88 s | 1.040 |
| asr.chunk | faster_whisper | 2.68 s | 6.80 s | 2.534 |
| asr.chunk | faster_whisper | 8.83 s | 9.18 s | 1.040 |
| asr.chunk | faster_whisper | 14.14 s | 9.77 s | 0.691 |
| asr.chunk | faster_whisper | 8.25 s | 7.91 s | 0.958 |
| asr.chunk | faster_whisper | 17.34 s | 10.50 s | 0.606 |
| asr.chunk | faster_whisper | 6.24 s | 7.91 s | 1.269 |
| asr.chunk | faster_whisper | 13.85 s | 9.85 s | 0.711 |
| asr.chunk | faster_whisper | 6.97 s | 9.56 s | 1.372 |
| asr.chunk | faster_whisper | 8.48 s | 8.68 s | 1.024 |
| asr.chunk | faster_whisper | 15.45 s | 9.84 s | 0.637 |
| asr.chunk | faster_whisper | 5.88 s | 8.82 s | 1.499 |
| asr.chunk | faster_whisper | 7.20 s | 8.14 s | 1.131 |
| asr.chunk | faster_whisper | 8.09 s | 8.02 s | 0.991 |
| asr.chunk | faster_whisper | 11.80 s | 9.15 s | 0.775 |
| asr.chunk | faster_whisper | 7.48 s | 8.66 s | 1.158 |
| asr.chunk | faster_whisper | 9.18 s | 8.62 s | 0.939 |
| asr.chunk | faster_whisper | 12.06 s | 9.66 s | 0.801 |
| asr.chunk | faster_whisper | 6.33 s | 7.83 s | 1.236 |
| asr.chunk | faster_whisper | 9.63 s | 9.24 s | 0.960 |
| asr.chunk | faster_whisper | 10.81 s | 8.85 s | 0.819 |
| asr.chunk | faster_whisper | 30.00 s | 16.91 s | 0.564 |
| asr.chunk | faster_whisper | 4.24 s | 6.97 s | 1.645 |
| asr.chunk | faster_whisper | 5.12 s | 7.61 s | 1.487 |
| asr.chunk | faster_whisper | 6.91 s | 7.74 s | 1.121 |
| asr.chunk | faster_whisper | 1.76 s | 6.43 s | 3.664 |
| asr.chunk | faster_whisper | 1.98 s | 6.89 s | 3.479 |

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
| infer | ok | 54.81 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.60 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 10.88 s | 4,887 | 0 | 0 | 879 | — (not_supported) |
| **total** |  | 2 |  |  | 11.48 s | 4,899 | 0 | 0 | 885 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,396,651,520 B (2.23 GiB) → 2,426,834,944 B (2.26 GiB) |
| swap used | 181,686,272 B (0.17 GiB) → 211,910,656 B (0.20 GiB) |
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

- Top critical-path stages: asr_primary 725.15 s (58.0 %); language_detection 439.63 s (35.2 %); diarization_infer 54.81 s (4.4 %).
- Reprocessing ratio: 0.894.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 0.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
