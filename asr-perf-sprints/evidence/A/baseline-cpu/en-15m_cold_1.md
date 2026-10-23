# Diagnostics — recording 62dad57f-0a37-4ee7-813b-66967b22852b

Run `e6755cbc-0640-4484-836c-1c7bc3a778e7` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 62dad57f-0a37-4ee7-813b-66967b22852b |
| processing_run_id | e6755cbc-0640-4484-836c-1c7bc3a778e7 |
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
| processing_wall_seconds | 1229.52 s |
| rtf | 1.378 |
| speedup | 0.726 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.25 s | 0.0 % | -0.25 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.19 s |
| other | worker_job | 1 | ok | 1201.10 s | — | +13.29 s |
| queue | · asr.queue_wait | 1 | ok | 13.29 s | 1.1 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.86 s | 0.1 % | +13.29 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +14.16 s |
| model_init | · vad.model | 1 | ok | 1.47 s | 0.1 % | +14.16 s |
| vad | · vad.speech_runs | 1 | ok | 25.27 s | 2.1 % | +15.63 s |
| language_detection | · lid.recording | 1 | ok | 5.05 s | 0.4 % | +40.91 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 0.4 % | +45.96 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 0.4 % | +50.80 s |
| language_detection | · lid.run | 1 | ok | 4.82 s | 0.4 % | +55.45 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 0.4 % | +60.27 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 0.4 % | +65.01 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +69.69 s |
| language_detection | · lid.run | 1 | ok | 4.86 s | 0.4 % | +74.35 s |
| language_detection | · lid.run | 1 | ok | 4.59 s | 0.4 % | +79.22 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 0.4 % | +83.81 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 0.4 % | +89.17 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 0.4 % | +94.06 s |
| language_detection | · lid.run | 1 | ok | 4.80 s | 0.4 % | +99.00 s |
| language_detection | · lid.run | 1 | ok | 4.96 s | 0.4 % | +103.80 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 0.4 % | +108.76 s |
| language_detection | · lid.run | 1 | ok | 4.91 s | 0.4 % | +113.53 s |
| language_detection | · lid.run | 1 | ok | 5.15 s | 0.4 % | +118.44 s |
| language_detection | · lid.run | 1 | ok | 4.95 s | 0.4 % | +123.60 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 0.4 % | +128.55 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +133.58 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 0.4 % | +138.82 s |
| language_detection | · lid.run | 1 | ok | 5.15 s | 0.4 % | +143.84 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 0.4 % | +148.99 s |
| language_detection | · lid.run | 1 | ok | 5.18 s | 0.4 % | +154.28 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +159.47 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +164.70 s |
| language_detection | · lid.run | 1 | ok | 5.11 s | 0.4 % | +169.94 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 0.4 % | +175.05 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +180.44 s |
| language_detection | · lid.run | 1 | ok | 5.32 s | 0.4 % | +185.96 s |
| language_detection | · lid.run | 1 | ok | 5.40 s | 0.4 % | +191.28 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 0.4 % | +196.69 s |
| language_detection | · lid.run | 1 | ok | 5.93 s | 0.5 % | +201.95 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.5 % | +207.88 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 0.4 % | +213.47 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +218.86 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +224.33 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 0.4 % | +229.81 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 0.4 % | +235.27 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.5 % | +240.56 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +246.13 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 0.4 % | +251.37 s |
| language_detection | · lid.run | 1 | ok | 5.24 s | 0.4 % | +256.74 s |
| language_detection | · lid.run | 1 | ok | 5.38 s | 0.4 % | +261.98 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +267.36 s |
| language_detection | · lid.run | 1 | ok | 5.39 s | 0.4 % | +272.69 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +278.08 s |
| language_detection | · lid.run | 1 | ok | 5.37 s | 0.4 % | +283.34 s |
| language_detection | · lid.run | 1 | ok | 5.17 s | 0.4 % | +288.71 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +293.88 s |
| language_detection | · lid.run | 1 | ok | 5.21 s | 0.4 % | +299.21 s |
| language_detection | · lid.run | 1 | ok | 5.28 s | 0.4 % | +304.43 s |
| language_detection | · lid.run | 1 | ok | 5.30 s | 0.4 % | +309.71 s |
| language_detection | · lid.run | 1 | ok | 5.65 s | 0.5 % | +315.01 s |
| language_detection | · lid.run | 1 | ok | 5.18 s | 0.4 % | +320.66 s |
| language_detection | · lid.run | 1 | ok | 5.76 s | 0.5 % | +325.84 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.5 % | +331.60 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 0.4 % | +337.16 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +342.52 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +347.85 s |
| language_detection | · lid.run | 1 | ok | 5.37 s | 0.4 % | +353.18 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +358.55 s |
| language_detection | · lid.run | 1 | ok | 5.46 s | 0.4 % | +363.80 s |
| language_detection | · lid.run | 1 | ok | 5.21 s | 0.4 % | +369.26 s |
| language_detection | · lid.run | 1 | ok | 5.31 s | 0.4 % | +374.47 s |
| language_detection | · lid.run | 1 | ok | 5.37 s | 0.4 % | +379.78 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +385.15 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 0.4 % | +390.40 s |
| language_detection | · lid.run | 1 | ok | 5.37 s | 0.4 % | +395.67 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +401.05 s |
| language_detection | · lid.run | 1 | ok | 5.32 s | 0.4 % | +406.30 s |
| language_detection | · lid.run | 1 | ok | 5.35 s | 0.4 % | +411.63 s |
| language_detection | · lid.run | 1 | ok | 5.16 s | 0.4 % | +416.97 s |
| language_detection | · lid.run | 1 | ok | 5.30 s | 0.4 % | +422.14 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +427.45 s |
| language_detection | · lid.run | 1 | ok | 5.34 s | 0.4 % | +432.91 s |
| language_detection | · lid.run | 1 | ok | 5.34 s | 0.4 % | +438.26 s |
| language_detection | · lid.run | 1 | ok | 5.35 s | 0.4 % | +443.60 s |
| language_detection | · lid.run | 1 | ok | 5.54 s | 0.5 % | +448.96 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 704.77 s | 57.3 % | +454.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.96 s | 0.8 % | +454.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.14 s | 0.7 % | +464.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.34 s | 0.6 % | +472.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.18 s | 0.7 % | +479.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.21 s | 0.6 % | +489.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.75 s | 0.7 % | +496.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.77 s | 0.6 % | +505.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.43 s | 0.7 % | +512.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 0.7 % | +521.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.17 s | 0.7 % | +529.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.17 s | 0.6 % | +538.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.12 s | 0.7 % | +545.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.13 s | 0.7 % | +554.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 0.7 % | +563.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.68 s | 1.1 % | +571.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.76 s | 0.9 % | +585.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.38 s | 0.6 % | +596.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.57 s | 0.7 % | +603.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.72 s | 0.5 % | +612.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.57 s | 1.0 % | +619.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.08 s | 0.8 % | +631.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.08 s | 0.6 % | +641.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.02 s | 0.7 % | +648.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.65 s | 0.6 % | +657.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.78 s | 0.8 % | +665.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.57 s | 0.7 % | +675.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.79 s | 0.8 % | +683.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.71 s | 0.8 % | +693.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.44 s | 0.8 % | +703.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.88 s | 0.9 % | +713.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.54 s | 0.9 % | +724.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.19 s | 0.8 % | +735.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.36 s | 0.7 % | +745.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.25 s | 0.6 % | +753.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.24 s | 0.8 % | +761.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.11 s | 0.7 % | +771.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.17 s | 0.7 % | +780.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.89 s | 0.6 % | +789.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.92 s | 1.0 % | +797.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.45 s | 0.7 % | +809.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.37 s | 0.7 % | +817.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.29 s | 0.8 % | +826.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.41 s | 0.6 % | +835.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.14 s | 0.6 % | +842.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.09 s | 0.7 % | +850.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.78 s | 0.6 % | +859.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.44 s | 0.7 % | +865.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.41 s | 0.7 % | +874.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.32 s | 0.6 % | +882.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 0.6 % | +890.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.37 s | 0.6 % | +898.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.54 s | 0.6 % | +905.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.58 s | 0.5 % | +913.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.43 s | 0.5 % | +919.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.85 s | 0.8 % | +926.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.59 s | 0.6 % | +935.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.60 s | 0.5 % | +943.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.59 s | 0.7 % | +950.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.29 s | 0.8 % | +958.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.82 s | 0.6 % | +968.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.75 s | 0.8 % | +975.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.49 s | 0.6 % | +985.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.34 s | 0.8 % | +993.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.97 s | 0.6 % | +1002.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.85 s | 0.6 % | +1010.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.50 s | 0.8 % | +1018.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.62 s | 0.6 % | +1027.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.48 s | 0.6 % | +1035.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.59 s | 0.6 % | +1042.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.95 s | 0.7 % | +1050.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.26 s | 0.7 % | +1059.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.06 s | 0.7 % | +1067.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.49 s | 0.8 % | +1075.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.41 s | 0.6 % | +1085.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.80 s | 0.7 % | +1092.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.45 s | 0.7 % | +1101.41 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.02 s | 1.2 % | +1109.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.83 s | 0.6 % | +1124.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.24 s | 0.6 % | +1131.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.57 s | 0.6 % | +1138.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.25 s | 0.5 % | +1146.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.50 s | 0.5 % | +1152.77 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +1159.27 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1159.32 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1159.40 s |
| diarization_load | · diarization.load | 1 | ok | 1.80 s | 0.1 % | +1159.40 s |
| diarization_infer | · diarization.infer | 1 | ok | 52.95 s | 4.3 % | +1161.20 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.18 s | 0.0 % | +1214.16 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1214.35 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +1214.35 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.41 s |
| queue | · asr.queue_wait | 1 | ok | 1214.40 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.41 s |
| queue | · asr.queue_wait | 1 | ok | 1214.41 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.41 s |
| queue | · asr.queue_wait | 1 | ok | 1214.41 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.41 s |
| queue | · asr.queue_wait | 1 | ok | 1214.41 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.42 s |
| queue | · asr.queue_wait | 1 | ok | 1214.42 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.42 s |
| queue | · asr.queue_wait | 1 | ok | 1214.42 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.42 s |
| queue | · asr.queue_wait | 1 | ok | 1214.42 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.43 s |
| queue | · asr.queue_wait | 1 | ok | 1214.42 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.43 s |
| queue | · asr.queue_wait | 1 | ok | 1214.43 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.43 s |
| queue | · asr.queue_wait | 1 | ok | 1214.43 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.43 s |
| queue | · asr.queue_wait | 1 | ok | 1214.43 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.44 s |
| queue | · asr.queue_wait | 1 | ok | 1214.43 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.44 s |
| queue | · asr.queue_wait | 1 | ok | 1214.44 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.44 s |
| queue | · asr.queue_wait | 1 | ok | 1214.44 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.44 s |
| queue | · asr.queue_wait | 1 | ok | 1214.44 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.45 s |
| queue | · asr.queue_wait | 1 | ok | 1214.44 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.45 s |
| queue | · asr.queue_wait | 1 | ok | 1214.45 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.45 s |
| queue | · asr.queue_wait | 1 | ok | 1214.45 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.45 s |
| queue | · asr.queue_wait | 1 | ok | 1214.45 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1214.46 s |
| queue | · asr.queue_wait | 1 | ok | 1214.45 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.65 s | 0.1 % | +1216.24 s |
| other | notes.generate | 1 | ok | 12.62 s | — | +1216.90 s |
| llm_call | · llm.note_write | 1 | ok | 12.49 s | 1.0 % | +1216.97 s |

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
| lid.recording | 90.00 s | 5.05 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 4.83 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 4.65 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 4.82 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 4.73 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 4.68 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 4.66 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 4.86 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 4.59 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.36 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 4.89 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 4.93 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 4.80 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 4.96 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 4.77 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 4.91 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.15 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 4.95 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.03 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.23 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.02 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 5.15 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.29 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 5.18 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 5.23 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.23 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 5.11 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 5.39 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 5.52 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 5.32 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 5.40 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 5.26 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 5.93 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 5.58 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 5.39 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 5.47 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.47 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 5.46 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 5.29 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.57 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 5.23 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 5.36 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 5.24 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 5.38 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 5.33 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 5.39 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.25 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.37 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 5.17 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 5.33 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 5.21 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 5.28 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 5.30 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 5.65 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 5.18 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 5.76 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 5.56 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 5.36 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 5.33 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.33 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 5.37 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 5.25 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 5.46 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 5.21 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 5.31 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 5.37 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 5.25 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 5.26 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 5.37 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 5.25 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 5.32 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 5.35 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 5.16 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 5.30 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 5.47 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 5.34 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.34 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 5.35 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 5.54 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 9.95 s | 0.647 |
| asr.chunk | faster_whisper | 8.73 s | 8.14 s | 0.932 |
| asr.chunk | faster_whisper | 4.28 s | 7.34 s | 1.714 |
| asr.chunk | faster_whisper | 16.38 s | 9.18 s | 0.560 |
| asr.chunk | faster_whisper | 4.54 s | 7.21 s | 1.589 |
| asr.chunk | faster_whisper | 13.53 s | 8.75 s | 0.647 |
| asr.chunk | faster_whisper | 8.12 s | 7.77 s | 0.956 |
| asr.chunk | faster_whisper | 10.59 s | 8.43 s | 0.796 |
| asr.chunk | faster_whisper | 7.90 s | 8.15 s | 1.032 |
| asr.chunk | faster_whisper | 13.28 s | 9.17 s | 0.691 |
| asr.chunk | faster_whisper | 4.48 s | 7.17 s | 1.602 |
| asr.chunk | faster_whisper | 13.12 s | 9.12 s | 0.695 |
| asr.chunk | faster_whisper | 7.48 s | 8.13 s | 1.086 |
| asr.chunk | faster_whisper | 6.24 s | 8.89 s | 1.425 |
| asr.chunk | faster_whisper | 28.38 s | 13.68 s | 0.482 |
| asr.chunk | faster_whisper | 16.28 s | 10.76 s | 0.660 |
| asr.chunk | faster_whisper | 7.04 s | 7.38 s | 1.049 |
| asr.chunk | faster_whisper | 9.63 s | 8.57 s | 0.890 |
| asr.chunk | faster_whisper | 2.49 s | 6.72 s | 2.695 |
| asr.chunk | faster_whisper | 24.16 s | 12.57 s | 0.520 |
| asr.chunk | faster_whisper | 16.64 s | 10.08 s | 0.606 |
| asr.chunk | faster_whisper | 1.28 s | 7.08 s | 5.550 |
| asr.chunk | faster_whisper | 11.71 s | 9.02 s | 0.770 |
| asr.chunk | faster_whisper | 6.46 s | 7.65 s | 1.185 |
| asr.chunk | faster_whisper | 15.71 s | 9.78 s | 0.622 |
| asr.chunk | faster_whisper | 8.73 s | 8.57 s | 0.982 |
| asr.chunk | faster_whisper | 13.47 s | 9.79 s | 0.727 |
| asr.chunk | faster_whisper | 6.84 s | 9.71 s | 1.418 |
| asr.chunk | faster_whisper | 17.82 s | 10.44 s | 0.586 |
| asr.chunk | faster_whisper | 11.61 s | 10.88 s | 0.937 |
| asr.chunk | faster_whisper | 11.10 s | 10.54 s | 0.950 |
| asr.chunk | faster_whisper | 12.41 s | 10.19 s | 0.821 |
| asr.chunk | faster_whisper | 6.24 s | 8.36 s | 1.340 |
| asr.chunk | faster_whisper | 1.82 s | 7.25 s | 3.982 |
| asr.chunk | faster_whisper | 13.85 s | 10.24 s | 0.739 |
| asr.chunk | faster_whisper | 12.44 s | 9.11 s | 0.732 |
| asr.chunk | faster_whisper | 10.84 s | 9.17 s | 0.845 |
| asr.chunk | faster_whisper | 8.96 s | 7.89 s | 0.881 |
| asr.chunk | faster_whisper | 20.76 s | 11.92 s | 0.574 |
| asr.chunk | faster_whisper | 5.98 s | 8.45 s | 1.413 |
| asr.chunk | faster_whisper | 7.77 s | 8.37 s | 1.077 |
| asr.chunk | faster_whisper | 11.87 s | 9.29 s | 0.782 |
| asr.chunk | faster_whisper | 4.48 s | 7.41 s | 1.655 |
| asr.chunk | faster_whisper | 5.53 s | 7.14 s | 1.290 |
| asr.chunk | faster_whisper | 11.64 s | 9.09 s | 0.781 |
| asr.chunk | faster_whisper | 3.00 s | 6.78 s | 2.258 |
| asr.chunk | faster_whisper | 11.39 s | 8.44 s | 0.742 |
| asr.chunk | faster_whisper | 11.77 s | 8.41 s | 0.715 |
| asr.chunk | faster_whisper | 4.48 s | 7.32 s | 1.635 |
| asr.chunk | faster_whisper | 8.64 s | 7.98 s | 0.924 |
| asr.chunk | faster_whisper | 6.01 s | 7.37 s | 1.226 |
| asr.chunk | faster_whisper | 8.03 s | 7.54 s | 0.940 |
| asr.chunk | faster_whisper | 2.56 s | 6.58 s | 2.575 |
| asr.chunk | faster_whisper | 2.49 s | 6.43 s | 2.579 |
| asr.chunk | faster_whisper | 13.44 s | 9.85 s | 0.733 |
| asr.chunk | faster_whisper | 7.58 s | 7.59 s | 1.001 |
| asr.chunk | faster_whisper | 2.68 s | 6.60 s | 2.458 |
| asr.chunk | faster_whisper | 8.83 s | 8.59 s | 0.973 |
| asr.chunk | faster_whisper | 14.14 s | 9.29 s | 0.657 |
| asr.chunk | faster_whisper | 8.25 s | 7.82 s | 0.948 |
| asr.chunk | faster_whisper | 17.34 s | 9.75 s | 0.562 |
| asr.chunk | faster_whisper | 6.24 s | 7.49 s | 1.201 |
| asr.chunk | faster_whisper | 13.85 s | 9.34 s | 0.674 |
| asr.chunk | faster_whisper | 6.97 s | 7.97 s | 1.143 |
| asr.chunk | faster_whisper | 8.48 s | 7.85 s | 0.926 |
| asr.chunk | faster_whisper | 15.45 s | 9.50 s | 0.615 |
| asr.chunk | faster_whisper | 5.88 s | 7.62 s | 1.296 |
| asr.chunk | faster_whisper | 7.20 s | 7.48 s | 1.040 |
| asr.chunk | faster_whisper | 8.09 s | 7.59 s | 0.937 |
| asr.chunk | faster_whisper | 11.80 s | 8.95 s | 0.758 |
| asr.chunk | faster_whisper | 7.48 s | 8.26 s | 1.104 |
| asr.chunk | faster_whisper | 9.18 s | 8.06 s | 0.878 |
| asr.chunk | faster_whisper | 12.06 s | 9.49 s | 0.787 |
| asr.chunk | faster_whisper | 6.33 s | 7.41 s | 1.170 |
| asr.chunk | faster_whisper | 9.63 s | 8.80 s | 0.914 |
| asr.chunk | faster_whisper | 10.81 s | 8.45 s | 0.781 |
| asr.chunk | faster_whisper | 30.00 s | 15.02 s | 0.501 |
| asr.chunk | faster_whisper | 4.24 s | 6.83 s | 1.611 |
| asr.chunk | faster_whisper | 5.12 s | 7.24 s | 1.415 |
| asr.chunk | faster_whisper | 6.91 s | 7.57 s | 1.095 |
| asr.chunk | faster_whisper | 1.76 s | 6.25 s | 3.557 |
| asr.chunk | faster_whisper | 1.98 s | 6.50 s | 3.281 |

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
| load | ok | 1.80 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 52.95 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.65 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 12.48 s | 4,887 | 0 | 0 | 999 | — (not_supported) |
| **total** |  | 2 |  |  | 13.14 s | 4,899 | 0 | 0 | 1,005 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,455,388,160 B (2.29 GiB) → 3,047,809,024 B (2.84 GiB) |
| swap used | 431,386,624 B (0.40 GiB) → 451,198,976 B (0.42 GiB) |
| memory pressure | some_avg10=0.22 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,608 B |

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

- Top critical-path stages: asr_primary 704.77 s (57.3 %); language_detection 413.43 s (33.6 %); diarization_infer 52.96 s (4.3 %).
- Reprocessing ratio: 0.894.
- Cold loads: vad.model 1.47 s; diarization.load 1.80 s.
- Queue wait: 13.29 s.
- LLM latency share of wall: 1.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
