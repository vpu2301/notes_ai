# Diagnostics — recording 3774cb53-85bc-4721-bf18-fd1062c8d4ae

Run `dcecdb81-7a47-4ceb-a59e-b73f8b844e07` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 3774cb53-85bc-4721-bf18-fd1062c8d4ae |
| processing_run_id | dcecdb81-7a47-4ceb-a59e-b73f8b844e07 |
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
| processing_wall_seconds | 1302.95 s |
| rtf | 1.460 |
| speedup | 0.685 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.22 s | 0.0 % | -0.22 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.15 s |
| other | worker_job | 1 | ok | 1290.87 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.45 s | 0.0 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.48 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.48 s |
| vad | · vad.speech_runs | 1 | ok | 15.15 s | 1.2 % | +0.48 s |
| language_detection | · lid.recording | 1 | ok | 5.30 s | 0.4 % | +15.63 s |
| language_detection | · lid.run | 1 | ok | 5.28 s | 0.4 % | +20.94 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 0.4 % | +26.23 s |
| language_detection | · lid.run | 1 | ok | 4.96 s | 0.4 % | +31.32 s |
| language_detection | · lid.run | 1 | ok | 5.11 s | 0.4 % | +36.28 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 0.4 % | +41.39 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 0.4 % | +46.37 s |
| language_detection | · lid.run | 1 | ok | 5.22 s | 0.4 % | +51.26 s |
| language_detection | · lid.run | 1 | ok | 6.11 s | 0.5 % | +56.48 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +62.60 s |
| language_detection | · lid.run | 1 | ok | 5.49 s | 0.4 % | +67.93 s |
| language_detection | · lid.run | 1 | ok | 5.21 s | 0.4 % | +73.43 s |
| language_detection | · lid.run | 1 | ok | 5.98 s | 0.5 % | +78.64 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +84.62 s |
| language_detection | · lid.run | 1 | ok | 5.40 s | 0.4 % | +90.13 s |
| language_detection | · lid.run | 1 | ok | 5.44 s | 0.4 % | +95.54 s |
| language_detection | · lid.run | 1 | ok | 5.79 s | 0.4 % | +100.98 s |
| language_detection | · lid.run | 1 | ok | 5.41 s | 0.4 % | +106.77 s |
| language_detection | · lid.run | 1 | ok | 5.68 s | 0.4 % | +112.18 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 0.4 % | +117.86 s |
| language_detection | · lid.run | 1 | ok | 5.86 s | 0.4 % | +123.23 s |
| language_detection | · lid.run | 1 | ok | 5.94 s | 0.5 % | +129.09 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.4 % | +135.04 s |
| language_detection | · lid.run | 1 | ok | 5.90 s | 0.5 % | +140.81 s |
| language_detection | · lid.run | 1 | ok | 5.90 s | 0.5 % | +146.71 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.4 % | +152.62 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 0.4 % | +158.39 s |
| language_detection | · lid.run | 1 | ok | 5.95 s | 0.5 % | +164.17 s |
| language_detection | · lid.run | 1 | ok | 6.21 s | 0.5 % | +170.12 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 0.5 % | +176.34 s |
| language_detection | · lid.run | 1 | ok | 6.51 s | 0.5 % | +182.37 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 0.4 % | +188.90 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 0.4 % | +194.68 s |
| language_detection | · lid.run | 1 | ok | 5.87 s | 0.5 % | +200.42 s |
| language_detection | · lid.run | 1 | ok | 6.01 s | 0.5 % | +206.29 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +212.31 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.4 % | +217.98 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +223.75 s |
| language_detection | · lid.run | 1 | ok | 5.72 s | 0.4 % | +229.37 s |
| language_detection | · lid.run | 1 | ok | 5.97 s | 0.5 % | +235.09 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +241.07 s |
| language_detection | · lid.run | 1 | ok | 6.18 s | 0.5 % | +246.68 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +252.87 s |
| language_detection | · lid.run | 1 | ok | 5.76 s | 0.4 % | +258.53 s |
| language_detection | · lid.run | 1 | ok | 6.48 s | 0.5 % | +264.30 s |
| language_detection | · lid.run | 1 | ok | 5.54 s | 0.4 % | +270.78 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +276.32 s |
| language_detection | · lid.run | 1 | ok | 5.60 s | 0.4 % | +281.98 s |
| language_detection | · lid.run | 1 | ok | 6.43 s | 0.5 % | +287.59 s |
| language_detection | · lid.run | 1 | ok | 5.80 s | 0.4 % | +294.03 s |
| language_detection | · lid.run | 1 | ok | 7.18 s | 0.6 % | +299.83 s |
| language_detection | · lid.run | 1 | ok | 5.89 s | 0.5 % | +307.03 s |
| language_detection | · lid.run | 1 | ok | 5.86 s | 0.4 % | +312.92 s |
| language_detection | · lid.run | 1 | ok | 5.64 s | 0.4 % | +318.78 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 0.4 % | +324.43 s |
| language_detection | · lid.run | 1 | ok | 5.60 s | 0.4 % | +330.24 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +335.85 s |
| language_detection | · lid.run | 1 | ok | 6.17 s | 0.5 % | +341.42 s |
| language_detection | · lid.run | 1 | ok | 6.41 s | 0.5 % | +347.59 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +354.00 s |
| language_detection | · lid.run | 1 | ok | 5.81 s | 0.4 % | +359.67 s |
| language_detection | · lid.run | 1 | ok | 6.03 s | 0.5 % | +365.56 s |
| language_detection | · lid.run | 1 | ok | 5.83 s | 0.4 % | +371.60 s |
| language_detection | · lid.run | 1 | ok | 5.73 s | 0.4 % | +377.43 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.4 % | +383.16 s |
| language_detection | · lid.run | 1 | ok | 6.23 s | 0.5 % | +388.74 s |
| language_detection | · lid.run | 1 | ok | 5.82 s | 0.4 % | +394.98 s |
| language_detection | · lid.run | 1 | ok | 6.12 s | 0.5 % | +400.80 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 0.4 % | +406.93 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +412.46 s |
| language_detection | · lid.run | 1 | ok | 5.80 s | 0.4 % | +418.12 s |
| language_detection | · lid.run | 1 | ok | 6.40 s | 0.5 % | +423.93 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 0.4 % | +430.33 s |
| language_detection | · lid.run | 1 | ok | 6.11 s | 0.5 % | +436.02 s |
| language_detection | · lid.run | 1 | ok | 5.82 s | 0.4 % | +442.13 s |
| language_detection | · lid.run | 1 | ok | 6.07 s | 0.5 % | +447.95 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +454.02 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 0.4 % | +459.59 s |
| language_detection | · lid.run | 1 | ok | 6.13 s | 0.5 % | +465.13 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 763.53 s | 58.6 % | +471.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.05 s | 0.8 % | +471.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.82 s | 0.7 % | +481.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.17 s | 0.6 % | +490.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 0.8 % | +498.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.22 s | 0.6 % | +508.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.45 s | 0.7 % | +516.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.00 s | 0.7 % | +525.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.55 s | 0.7 % | +534.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.33 s | 0.7 % | +544.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.76 s | 0.7 % | +553.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.63 s | 0.6 % | +563.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.84 s | 0.8 % | +571.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.35 s | 0.6 % | +581.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.37 s | 0.6 % | +589.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.59 s | 1.1 % | +597.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.88 s | 0.9 % | +612.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.13 s | 0.6 % | +624.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.30 s | 0.7 % | +632.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.14 s | 0.5 % | +641.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.83 s | 1.1 % | +648.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.48 s | 0.9 % | +662.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.80 s | 0.5 % | +674.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.04 s | 0.7 % | +680.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.96 s | 0.6 % | +690.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 0.8 % | +697.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.55 s | 0.7 % | +707.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.50 s | 0.7 % | +717.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.60 s | 0.7 % | +726.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.79 s | 0.8 % | +735.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.86 s | 0.8 % | +746.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.70 s | 0.7 % | +756.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.34 s | 0.8 % | +765.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.99 s | 0.7 % | +776.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.58 s | 0.6 % | +785.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.39 s | 0.8 % | +792.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.66 s | 0.7 % | +803.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.37 s | 0.7 % | +812.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.03 s | 0.6 % | +822.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.36 s | 1.0 % | +830.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.39 s | 0.6 % | +843.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.64 s | 0.7 % | +852.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.97 s | 0.8 % | +860.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.58 s | 0.6 % | +871.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.92 s | 0.6 % | +879.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.13 s | 0.8 % | +887.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.49 s | 0.6 % | +897.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.12 s | 0.8 % | +904.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.79 s | 0.8 % | +914.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.17 s | 0.6 % | +924.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.98 s | 0.7 % | +932.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 0.6 % | +941.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.64 s | 0.7 % | +950.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.53 s | 0.6 % | +958.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.44 s | 0.6 % | +966.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.17 s | 0.8 % | +973.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.69 s | 0.7 % | +983.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.73 s | 0.6 % | +992.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.69 s | 0.7 % | +1000.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.51 s | 0.8 % | +1010.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.40 s | 0.6 % | +1020.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.72 s | 0.9 % | +1028.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.22 s | 0.6 % | +1040.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.87 s | 0.8 % | +1048.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.72 s | 0.7 % | +1058.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.84 s | 0.7 % | +1067.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.25 s | 0.8 % | +1076.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 0.7 % | +1086.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.96 s | 0.6 % | +1095.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.77 s | 0.7 % | +1103.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 0.7 % | +1112.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.09 s | 0.7 % | +1122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.07 s | 0.7 % | +1131.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.06 s | 0.8 % | +1140.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.97 s | 0.7 % | +1150.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.90 s | 0.8 % | +1159.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.32 s | 0.7 % | +1169.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.93 s | 1.4 % | +1178.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.94 s | 0.6 % | +1196.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.03 s | 0.6 % | +1204.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.41 s | 0.6 % | +1212.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.49 s | 0.5 % | +1220.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.51 s | 0.6 % | +1227.29 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +1234.81 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1234.84 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1234.96 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +1234.97 s |
| diarization_infer | · diarization.infer | 1 | ok | 55.70 s | 4.3 % | +1234.97 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.19 s | 0.0 % | +1290.67 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1290.86 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +1290.86 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.93 s |
| queue | · asr.queue_wait | 1 | ok | 1290.92 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.93 s |
| queue | · asr.queue_wait | 1 | ok | 1290.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.93 s |
| queue | · asr.queue_wait | 1 | ok | 1290.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.94 s |
| queue | · asr.queue_wait | 1 | ok | 1290.93 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.94 s |
| queue | · asr.queue_wait | 1 | ok | 1290.94 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.95 s |
| queue | · asr.queue_wait | 1 | ok | 1290.94 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.95 s |
| queue | · asr.queue_wait | 1 | ok | 1290.95 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.96 s |
| queue | · asr.queue_wait | 1 | ok | 1290.95 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.96 s |
| queue | · asr.queue_wait | 1 | ok | 1290.96 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.96 s |
| queue | · asr.queue_wait | 1 | ok | 1290.96 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.97 s |
| queue | · asr.queue_wait | 1 | ok | 1290.96 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.97 s |
| queue | · asr.queue_wait | 1 | ok | 1290.97 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.98 s |
| queue | · asr.queue_wait | 1 | ok | 1290.97 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.98 s |
| queue | · asr.queue_wait | 1 | ok | 1290.98 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.98 s |
| queue | · asr.queue_wait | 1 | ok | 1290.98 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.99 s |
| queue | · asr.queue_wait | 1 | ok | 1290.98 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1290.99 s |
| queue | · asr.queue_wait | 1 | ok | 1290.99 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1291.00 s |
| queue | · asr.queue_wait | 1 | ok | 1290.99 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1291.00 s |
| queue | · asr.queue_wait | 1 | ok | 1291.00 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1291.00 s |
| queue | · asr.queue_wait | 1 | ok | 1291.00 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1291.01 s |
| queue | · asr.queue_wait | 1 | ok | 1291.00 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.75 s | 0.1 % | +1292.00 s |
| other | notes.generate | 1 | ok | 10.19 s | — | +1292.76 s |
| llm_call | · llm.note_write | 1 | ok | 10.08 s | 0.8 % | +1292.82 s |

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
| lid.recording | 90.00 s | 5.30 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 5.28 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 5.08 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 4.96 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 5.11 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 4.98 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 4.89 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 5.22 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 6.11 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.33 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 5.49 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 5.21 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.98 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 5.51 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.40 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 5.44 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.79 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.41 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.68 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.36 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.86 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 5.94 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.77 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 5.90 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 5.90 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.77 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 5.78 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 5.95 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 6.21 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 6.03 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 6.51 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 5.78 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 5.74 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 5.87 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 6.01 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 5.67 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.77 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 5.62 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 5.72 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.97 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 5.62 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 6.18 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 5.66 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 5.76 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 6.48 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 5.54 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.66 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.60 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 6.43 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 5.80 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 7.18 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 5.89 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 5.86 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 5.64 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 5.81 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 5.60 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 5.57 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 6.17 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 6.41 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.66 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 5.81 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 6.03 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 5.83 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 5.73 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 5.58 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 6.23 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 5.82 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 6.12 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 5.53 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 5.66 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 5.80 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 6.40 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 5.69 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 6.11 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 5.82 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 6.07 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.57 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 5.53 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 6.13 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 10.05 s | 0.653 |
| asr.chunk | faster_whisper | 8.73 s | 8.82 s | 1.010 |
| asr.chunk | faster_whisper | 4.28 s | 8.17 s | 1.906 |
| asr.chunk | faster_whisper | 16.38 s | 9.89 s | 0.604 |
| asr.chunk | faster_whisper | 4.54 s | 8.22 s | 1.811 |
| asr.chunk | faster_whisper | 13.53 s | 9.45 s | 0.698 |
| asr.chunk | faster_whisper | 8.12 s | 9.00 s | 1.108 |
| asr.chunk | faster_whisper | 10.59 s | 9.55 s | 0.902 |
| asr.chunk | faster_whisper | 7.90 s | 9.33 s | 1.181 |
| asr.chunk | faster_whisper | 13.28 s | 9.76 s | 0.735 |
| asr.chunk | faster_whisper | 4.48 s | 7.63 s | 1.705 |
| asr.chunk | faster_whisper | 13.12 s | 9.84 s | 0.750 |
| asr.chunk | faster_whisper | 7.48 s | 8.35 s | 1.115 |
| asr.chunk | faster_whisper | 6.24 s | 8.37 s | 1.342 |
| asr.chunk | faster_whisper | 28.38 s | 14.59 s | 0.514 |
| asr.chunk | faster_whisper | 16.28 s | 11.88 s | 0.730 |
| asr.chunk | faster_whisper | 7.04 s | 8.13 s | 1.156 |
| asr.chunk | faster_whisper | 9.63 s | 9.30 s | 0.966 |
| asr.chunk | faster_whisper | 2.49 s | 7.14 s | 2.866 |
| asr.chunk | faster_whisper | 24.16 s | 13.83 s | 0.572 |
| asr.chunk | faster_whisper | 16.64 s | 11.48 s | 0.690 |
| asr.chunk | faster_whisper | 1.28 s | 6.80 s | 5.333 |
| asr.chunk | faster_whisper | 11.71 s | 9.04 s | 0.772 |
| asr.chunk | faster_whisper | 6.46 s | 7.96 s | 1.232 |
| asr.chunk | faster_whisper | 15.71 s | 9.88 s | 0.629 |
| asr.chunk | faster_whisper | 8.73 s | 9.55 s | 1.093 |
| asr.chunk | faster_whisper | 13.47 s | 9.50 s | 0.706 |
| asr.chunk | faster_whisper | 6.84 s | 8.60 s | 1.256 |
| asr.chunk | faster_whisper | 17.82 s | 10.79 s | 0.606 |
| asr.chunk | faster_whisper | 11.61 s | 9.86 s | 0.849 |
| asr.chunk | faster_whisper | 11.10 s | 9.70 s | 0.874 |
| asr.chunk | faster_whisper | 12.41 s | 10.34 s | 0.833 |
| asr.chunk | faster_whisper | 6.24 s | 8.99 s | 1.441 |
| asr.chunk | faster_whisper | 1.82 s | 7.58 s | 4.165 |
| asr.chunk | faster_whisper | 13.85 s | 10.39 s | 0.750 |
| asr.chunk | faster_whisper | 12.44 s | 9.66 s | 0.776 |
| asr.chunk | faster_whisper | 10.84 s | 9.37 s | 0.864 |
| asr.chunk | faster_whisper | 8.96 s | 8.03 s | 0.897 |
| asr.chunk | faster_whisper | 20.76 s | 13.36 s | 0.644 |
| asr.chunk | faster_whisper | 5.98 s | 8.39 s | 1.402 |
| asr.chunk | faster_whisper | 7.77 s | 8.64 s | 1.112 |
| asr.chunk | faster_whisper | 11.87 s | 10.97 s | 0.924 |
| asr.chunk | faster_whisper | 4.48 s | 7.58 s | 1.694 |
| asr.chunk | faster_whisper | 5.53 s | 7.91 s | 1.431 |
| asr.chunk | faster_whisper | 11.64 s | 10.13 s | 0.870 |
| asr.chunk | faster_whisper | 3.00 s | 7.49 s | 2.494 |
| asr.chunk | faster_whisper | 11.39 s | 10.12 s | 0.888 |
| asr.chunk | faster_whisper | 11.77 s | 9.78 s | 0.831 |
| asr.chunk | faster_whisper | 4.48 s | 8.17 s | 1.826 |
| asr.chunk | faster_whisper | 8.64 s | 8.98 s | 1.040 |
| asr.chunk | faster_whisper | 6.01 s | 8.16 s | 1.357 |
| asr.chunk | faster_whisper | 8.03 s | 8.64 s | 1.076 |
| asr.chunk | faster_whisper | 2.56 s | 7.53 s | 2.944 |
| asr.chunk | faster_whisper | 2.49 s | 7.44 s | 2.986 |
| asr.chunk | faster_whisper | 13.44 s | 10.17 s | 0.757 |
| asr.chunk | faster_whisper | 7.58 s | 8.69 s | 1.147 |
| asr.chunk | faster_whisper | 2.68 s | 7.73 s | 2.879 |
| asr.chunk | faster_whisper | 8.83 s | 9.69 s | 1.098 |
| asr.chunk | faster_whisper | 14.14 s | 10.51 s | 0.743 |
| asr.chunk | faster_whisper | 8.25 s | 8.40 s | 1.018 |
| asr.chunk | faster_whisper | 17.34 s | 11.72 s | 0.676 |
| asr.chunk | faster_whisper | 6.24 s | 8.22 s | 1.318 |
| asr.chunk | faster_whisper | 13.85 s | 9.87 s | 0.712 |
| asr.chunk | faster_whisper | 6.97 s | 8.72 s | 1.250 |
| asr.chunk | faster_whisper | 8.48 s | 8.84 s | 1.043 |
| asr.chunk | faster_whisper | 15.45 s | 10.25 s | 0.663 |
| asr.chunk | faster_whisper | 5.88 s | 8.96 s | 1.523 |
| asr.chunk | faster_whisper | 7.20 s | 7.96 s | 1.106 |
| asr.chunk | faster_whisper | 8.09 s | 8.77 s | 1.084 |
| asr.chunk | faster_whisper | 11.80 s | 9.68 s | 0.820 |
| asr.chunk | faster_whisper | 7.48 s | 9.09 s | 1.215 |
| asr.chunk | faster_whisper | 9.18 s | 9.07 s | 0.988 |
| asr.chunk | faster_whisper | 12.06 s | 10.06 s | 0.834 |
| asr.chunk | faster_whisper | 6.33 s | 8.97 s | 1.416 |
| asr.chunk | faster_whisper | 9.63 s | 9.90 s | 1.028 |
| asr.chunk | faster_whisper | 10.81 s | 9.32 s | 0.862 |
| asr.chunk | faster_whisper | 30.00 s | 17.93 s | 0.598 |
| asr.chunk | faster_whisper | 4.24 s | 7.94 s | 1.875 |
| asr.chunk | faster_whisper | 5.12 s | 8.03 s | 1.569 |
| asr.chunk | faster_whisper | 6.91 s | 8.41 s | 1.217 |
| asr.chunk | faster_whisper | 1.76 s | 6.49 s | 3.698 |
| asr.chunk | faster_whisper | 1.98 s | 7.51 s | 3.794 |

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
| infer | ok | 55.69 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.75 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 10.07 s | 4,887 | 0 | 0 | 803 | — (not_supported) |
| **total** |  | 2 |  |  | 10.83 s | 4,899 | 0 | 0 | 809 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,394,497,024 B (2.23 GiB) → 2,415,673,344 B (2.25 GiB) |
| swap used | 293,998,592 B (0.27 GiB) → 329,834,496 B (0.31 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 2,030 B |

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

- Top critical-path stages: asr_primary 763.55 s (58.6 %); language_detection 455.30 s (34.9 %); diarization_infer 55.70 s (4.3 %).
- Reprocessing ratio: 0.894.
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: 0.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
