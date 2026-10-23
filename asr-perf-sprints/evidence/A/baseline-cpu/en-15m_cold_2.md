# Diagnostics — recording e82b9be8-05e6-4dd7-817c-592481d69245

Run `3cbaff6e-605f-4a4c-b992-4128a5383b5e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | e82b9be8-05e6-4dd7-817c-592481d69245 |
| processing_run_id | 3cbaff6e-605f-4a4c-b992-4128a5383b5e |
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
| processing_wall_seconds | 1160.22 s |
| rtf | 1.300 |
| speedup | 0.769 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.32 s | 0.0 % | -0.33 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.20 s |
| other | worker_job | 1 | ok | 1125.13 s | — | +16.32 s |
| queue | · asr.queue_wait | 1 | ok | 16.30 s | 1.4 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.01 s | 0.1 % | +16.33 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +17.35 s |
| model_init | · vad.model | 1 | ok | 1.50 s | 0.1 % | +17.35 s |
| vad | · vad.speech_runs | 1 | ok | 27.95 s | 2.4 % | +18.85 s |
| language_detection | · lid.recording | 1 | ok | 5.16 s | 0.4 % | +46.81 s |
| language_detection | · lid.run | 1 | ok | 4.55 s | 0.4 % | +51.98 s |
| language_detection | · lid.run | 1 | ok | 4.49 s | 0.4 % | +56.53 s |
| language_detection | · lid.run | 1 | ok | 4.64 s | 0.4 % | +61.02 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 0.4 % | +65.67 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 0.4 % | +70.36 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +74.93 s |
| language_detection | · lid.run | 1 | ok | 4.63 s | 0.4 % | +79.59 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 0.4 % | +84.22 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 0.4 % | +88.90 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 0.4 % | +93.80 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 0.4 % | +98.58 s |
| language_detection | · lid.run | 1 | ok | 4.71 s | 0.4 % | +103.57 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 0.4 % | +108.28 s |
| language_detection | · lid.run | 1 | ok | 4.99 s | 0.4 % | +112.93 s |
| language_detection | · lid.run | 1 | ok | 4.99 s | 0.4 % | +117.93 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 0.4 % | +122.93 s |
| language_detection | · lid.run | 1 | ok | 4.95 s | 0.4 % | +127.82 s |
| language_detection | · lid.run | 1 | ok | 5.04 s | 0.4 % | +132.77 s |
| language_detection | · lid.run | 1 | ok | 5.04 s | 0.4 % | +137.81 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 0.4 % | +142.85 s |
| language_detection | · lid.run | 1 | ok | 5.34 s | 0.5 % | +147.95 s |
| language_detection | · lid.run | 1 | ok | 5.07 s | 0.4 % | +153.29 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 0.4 % | +158.37 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 0.4 % | +163.35 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 0.4 % | +168.37 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 0.4 % | +173.47 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 0.4 % | +178.37 s |
| language_detection | · lid.run | 1 | ok | 4.62 s | 0.4 % | +183.06 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 0.4 % | +187.68 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 0.4 % | +192.29 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 0.4 % | +196.91 s |
| language_detection | · lid.run | 1 | ok | 4.55 s | 0.4 % | +201.59 s |
| language_detection | · lid.run | 1 | ok | 4.63 s | 0.4 % | +206.14 s |
| language_detection | · lid.run | 1 | ok | 4.58 s | 0.4 % | +210.77 s |
| language_detection | · lid.run | 1 | ok | 4.59 s | 0.4 % | +215.35 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 0.4 % | +219.94 s |
| language_detection | · lid.run | 1 | ok | 4.72 s | 0.4 % | +224.51 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 0.4 % | +229.23 s |
| language_detection | · lid.run | 1 | ok | 4.88 s | 0.4 % | +233.93 s |
| language_detection | · lid.run | 1 | ok | 4.72 s | 0.4 % | +238.81 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +243.53 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +248.19 s |
| language_detection | · lid.run | 1 | ok | 4.63 s | 0.4 % | +252.85 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 0.4 % | +257.48 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 0.4 % | +262.25 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 0.4 % | +266.86 s |
| language_detection | · lid.run | 1 | ok | 4.62 s | 0.4 % | +271.55 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +276.17 s |
| language_detection | · lid.run | 1 | ok | 4.58 s | 0.4 % | +280.84 s |
| language_detection | · lid.run | 1 | ok | 4.74 s | 0.4 % | +285.42 s |
| language_detection | · lid.run | 1 | ok | 4.69 s | 0.4 % | +290.16 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 0.4 % | +294.85 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 0.4 % | +299.42 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 0.4 % | +304.07 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 0.4 % | +308.81 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 0.4 % | +313.46 s |
| language_detection | · lid.run | 1 | ok | 4.76 s | 0.4 % | +318.15 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 0.4 % | +322.91 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 0.4 % | +327.56 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 0.4 % | +332.63 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 0.4 % | +337.28 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 0.4 % | +342.06 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 0.4 % | +346.83 s |
| language_detection | · lid.run | 1 | ok | 4.82 s | 0.4 % | +351.56 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 0.4 % | +356.38 s |
| language_detection | · lid.run | 1 | ok | 4.95 s | 0.4 % | +361.29 s |
| language_detection | · lid.run | 1 | ok | 4.76 s | 0.4 % | +366.24 s |
| language_detection | · lid.run | 1 | ok | 4.70 s | 0.4 % | +371.00 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 0.4 % | +375.71 s |
| language_detection | · lid.run | 1 | ok | 4.82 s | 0.4 % | +380.61 s |
| language_detection | · lid.run | 1 | ok | 4.71 s | 0.4 % | +385.43 s |
| language_detection | · lid.run | 1 | ok | 4.72 s | 0.4 % | +390.15 s |
| language_detection | · lid.run | 1 | ok | 4.81 s | 0.4 % | +394.86 s |
| language_detection | · lid.run | 1 | ok | 4.75 s | 0.4 % | +399.68 s |
| language_detection | · lid.run | 1 | ok | 4.80 s | 0.4 % | +404.43 s |
| language_detection | · lid.run | 1 | ok | 5.04 s | 0.4 % | +409.23 s |
| language_detection | · lid.run | 1 | ok | 4.75 s | 0.4 % | +414.28 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 0.4 % | +419.03 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 662.59 s | 57.1 % | +423.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.71 s | 0.8 % | +423.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.16 s | 0.6 % | +432.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.86 s | 0.6 % | +439.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.33 s | 0.7 % | +446.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.44 s | 0.6 % | +454.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.74 s | 0.7 % | +461.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.20 s | 0.6 % | +469.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.91 s | 0.7 % | +476.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.49 s | 0.6 % | +484.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.53 s | 0.7 % | +491.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.68 s | 0.6 % | +500.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 0.7 % | +506.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.41 s | 0.6 % | +514.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.69 s | 0.6 % | +522.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.61 s | 1.0 % | +528.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.24 s | 0.8 % | +540.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.87 s | 0.6 % | +549.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.70 s | 0.7 % | +556.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.38 s | 0.5 % | +564.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.49 s | 1.0 % | +570.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.13 s | 0.8 % | +582.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.02 s | 0.5 % | +591.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.63 s | 0.7 % | +597.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.20 s | 0.6 % | +605.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.14 s | 0.8 % | +613.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.76 s | 0.8 % | +622.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.35 s | 0.9 % | +631.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.97 s | 0.7 % | +641.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.63 s | 0.8 % | +649.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.68 s | 0.7 % | +659.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.02 s | 0.8 % | +667.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.06 s | 0.8 % | +676.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.44 s | 0.6 % | +685.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.18 s | 0.5 % | +693.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.79 s | 0.8 % | +699.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.40 s | 0.7 % | +708.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.20 s | 0.8 % | +716.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.69 s | 0.7 % | +725.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.92 s | 0.9 % | +733.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.43 s | 0.6 % | +744.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.66 s | 0.7 % | +751.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.86 s | 0.8 % | +759.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.79 s | 0.6 % | +768.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.00 s | 0.6 % | +775.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.70 s | 0.8 % | +782.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.38 s | 0.6 % | +790.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.09 s | 0.7 % | +797.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.20 s | 0.7 % | +805.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.02 s | 0.6 % | +813.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.67 s | 0.7 % | +820.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.15 s | 0.6 % | +828.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.74 s | 0.7 % | +835.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.52 s | 0.6 % | +843.21 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.49 s | 0.6 % | +849.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.06 s | 0.8 % | +856.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.38 s | 0.6 % | +865.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.34 s | 0.5 % | +872.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.48 s | 0.7 % | +879.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.87 s | 0.8 % | +887.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.50 s | 0.6 % | +896.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.77 s | 0.8 % | +903.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.32 s | 0.6 % | +913.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.02 s | 0.8 % | +920.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.93 s | 0.7 % | +929.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.95 s | 0.7 % | +937.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.31 s | 0.8 % | +945.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.02 s | 0.7 % | +955.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.21 s | 0.6 % | +963.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.86 s | 0.7 % | +970.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.29 s | 0.7 % | +978.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.08 s | 0.7 % | +986.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.20 s | 0.7 % | +994.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.35 s | 0.8 % | +1002.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.48 s | 0.6 % | +1012.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.76 s | 0.8 % | +1019.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.68 s | 0.7 % | +1028.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.96 s | 1.3 % | +1037.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.69 s | 0.6 % | +1052.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.44 s | 0.6 % | +1058.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.41 s | 0.6 % | +1066.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.08 s | 0.5 % | +1073.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.64 s | 0.6 % | +1079.71 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +1086.35 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1086.39 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1086.47 s |
| diarization_load | · diarization.load | 1 | ok | 1.92 s | 0.2 % | +1086.47 s |
| diarization_infer | · diarization.infer | 1 | ok | 52.78 s | 4.5 % | +1088.39 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.19 s | 0.0 % | +1141.18 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1141.37 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +1141.38 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.47 s |
| queue | · asr.queue_wait | 1 | ok | 1141.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.47 s |
| queue | · asr.queue_wait | 1 | ok | 1141.46 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.48 s |
| queue | · asr.queue_wait | 1 | ok | 1141.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.48 s |
| queue | · asr.queue_wait | 1 | ok | 1141.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.48 s |
| queue | · asr.queue_wait | 1 | ok | 1141.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.49 s |
| queue | · asr.queue_wait | 1 | ok | 1141.47 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.49 s |
| queue | · asr.queue_wait | 1 | ok | 1141.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.49 s |
| queue | · asr.queue_wait | 1 | ok | 1141.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.50 s |
| queue | · asr.queue_wait | 1 | ok | 1141.48 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.50 s |
| queue | · asr.queue_wait | 1 | ok | 1141.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.50 s |
| queue | · asr.queue_wait | 1 | ok | 1141.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.51 s |
| queue | · asr.queue_wait | 1 | ok | 1141.49 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.51 s |
| queue | · asr.queue_wait | 1 | ok | 1141.50 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.52 s |
| queue | · asr.queue_wait | 1 | ok | 1141.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.52 s |
| queue | · asr.queue_wait | 1 | ok | 1141.51 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.53 s |
| queue | · asr.queue_wait | 1 | ok | 1141.52 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.54 s |
| queue | · asr.queue_wait | 1 | ok | 1141.53 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1141.54 s |
| queue | · asr.queue_wait | 1 | ok | 1141.53 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 1.86 s | 0.2 % | +1142.72 s |
| other | notes.generate | 1 | ok | 15.63 s | — | +1144.58 s |
| llm_call | · llm.note_write | 1 | ok | 15.51 s | 1.3 % | +1144.65 s |

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
| lid.recording | 90.00 s | 5.16 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 4.55 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 4.49 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 4.64 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 4.69 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 4.57 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 4.66 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 4.63 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 4.68 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 4.90 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 4.78 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 4.98 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 4.71 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 4.65 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 4.99 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 4.99 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 4.89 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 4.95 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.04 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.04 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.10 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 5.34 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.07 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 4.98 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 5.03 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.09 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 4.90 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 4.69 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 4.62 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 4.61 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 4.61 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 4.68 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 4.55 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 4.63 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 4.58 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 4.59 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 4.57 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 4.72 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 4.69 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 4.88 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 4.72 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 4.66 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 4.66 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 4.63 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 4.78 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 4.61 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 4.69 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 4.62 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 4.66 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 4.58 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 4.74 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 4.69 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 4.57 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 4.65 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 4.73 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 4.66 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 4.68 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 4.76 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 4.65 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.06 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 4.65 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 4.78 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 4.77 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 4.73 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 4.82 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 4.90 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 4.95 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 4.76 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 4.70 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 4.90 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 4.82 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 4.71 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 4.72 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 4.81 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 4.75 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 4.80 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.04 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 4.75 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 4.73 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 8.71 s | 0.566 |
| asr.chunk | faster_whisper | 8.73 s | 7.16 s | 0.820 |
| asr.chunk | faster_whisper | 4.28 s | 6.86 s | 1.601 |
| asr.chunk | faster_whisper | 16.38 s | 8.33 s | 0.509 |
| asr.chunk | faster_whisper | 4.54 s | 6.44 s | 1.417 |
| asr.chunk | faster_whisper | 13.53 s | 7.74 s | 0.572 |
| asr.chunk | faster_whisper | 8.12 s | 7.20 s | 0.886 |
| asr.chunk | faster_whisper | 10.59 s | 7.91 s | 0.747 |
| asr.chunk | faster_whisper | 7.90 s | 7.49 s | 0.948 |
| asr.chunk | faster_whisper | 13.28 s | 8.53 s | 0.643 |
| asr.chunk | faster_whisper | 4.48 s | 6.68 s | 1.491 |
| asr.chunk | faster_whisper | 13.12 s | 7.98 s | 0.609 |
| asr.chunk | faster_whisper | 7.48 s | 7.41 s | 0.990 |
| asr.chunk | faster_whisper | 6.24 s | 6.69 s | 1.073 |
| asr.chunk | faster_whisper | 28.38 s | 11.61 s | 0.409 |
| asr.chunk | faster_whisper | 16.28 s | 9.24 s | 0.567 |
| asr.chunk | faster_whisper | 7.04 s | 6.87 s | 0.976 |
| asr.chunk | faster_whisper | 9.63 s | 7.70 s | 0.800 |
| asr.chunk | faster_whisper | 2.49 s | 6.38 s | 2.560 |
| asr.chunk | faster_whisper | 24.16 s | 11.49 s | 0.476 |
| asr.chunk | faster_whisper | 16.64 s | 9.13 s | 0.549 |
| asr.chunk | faster_whisper | 1.28 s | 6.02 s | 4.718 |
| asr.chunk | faster_whisper | 11.71 s | 8.63 s | 0.737 |
| asr.chunk | faster_whisper | 6.46 s | 7.20 s | 1.114 |
| asr.chunk | faster_whisper | 15.71 s | 9.14 s | 0.582 |
| asr.chunk | faster_whisper | 8.73 s | 8.76 s | 1.004 |
| asr.chunk | faster_whisper | 13.47 s | 10.35 s | 0.769 |
| asr.chunk | faster_whisper | 6.84 s | 7.96 s | 1.164 |
| asr.chunk | faster_whisper | 17.82 s | 9.63 s | 0.540 |
| asr.chunk | faster_whisper | 11.61 s | 8.68 s | 0.748 |
| asr.chunk | faster_whisper | 11.10 s | 9.02 s | 0.812 |
| asr.chunk | faster_whisper | 12.41 s | 9.06 s | 0.730 |
| asr.chunk | faster_whisper | 6.24 s | 7.44 s | 1.193 |
| asr.chunk | faster_whisper | 1.82 s | 6.18 s | 3.393 |
| asr.chunk | faster_whisper | 13.85 s | 8.79 s | 0.635 |
| asr.chunk | faster_whisper | 12.44 s | 8.40 s | 0.675 |
| asr.chunk | faster_whisper | 10.84 s | 9.20 s | 0.848 |
| asr.chunk | faster_whisper | 8.96 s | 7.69 s | 0.859 |
| asr.chunk | faster_whisper | 20.76 s | 10.92 s | 0.526 |
| asr.chunk | faster_whisper | 5.98 s | 7.42 s | 1.242 |
| asr.chunk | faster_whisper | 7.77 s | 7.66 s | 0.986 |
| asr.chunk | faster_whisper | 11.87 s | 8.86 s | 0.747 |
| asr.chunk | faster_whisper | 4.48 s | 6.79 s | 1.516 |
| asr.chunk | faster_whisper | 5.53 s | 7.00 s | 1.266 |
| asr.chunk | faster_whisper | 11.64 s | 8.70 s | 0.747 |
| asr.chunk | faster_whisper | 3.00 s | 6.38 s | 2.124 |
| asr.chunk | faster_whisper | 11.39 s | 8.09 s | 0.711 |
| asr.chunk | faster_whisper | 11.77 s | 8.20 s | 0.697 |
| asr.chunk | faster_whisper | 4.48 s | 7.02 s | 1.567 |
| asr.chunk | faster_whisper | 8.64 s | 7.67 s | 0.888 |
| asr.chunk | faster_whisper | 6.01 s | 7.15 s | 1.190 |
| asr.chunk | faster_whisper | 8.03 s | 7.74 s | 0.965 |
| asr.chunk | faster_whisper | 2.56 s | 6.52 s | 2.551 |
| asr.chunk | faster_whisper | 2.49 s | 6.49 s | 2.605 |
| asr.chunk | faster_whisper | 13.44 s | 9.06 s | 0.675 |
| asr.chunk | faster_whisper | 7.58 s | 7.38 s | 0.973 |
| asr.chunk | faster_whisper | 2.68 s | 6.34 s | 2.362 |
| asr.chunk | faster_whisper | 8.83 s | 8.48 s | 0.961 |
| asr.chunk | faster_whisper | 14.14 s | 8.87 s | 0.627 |
| asr.chunk | faster_whisper | 8.25 s | 7.50 s | 0.909 |
| asr.chunk | faster_whisper | 17.34 s | 9.77 s | 0.563 |
| asr.chunk | faster_whisper | 6.24 s | 7.32 s | 1.173 |
| asr.chunk | faster_whisper | 13.85 s | 9.02 s | 0.652 |
| asr.chunk | faster_whisper | 6.97 s | 7.93 s | 1.138 |
| asr.chunk | faster_whisper | 8.48 s | 7.95 s | 0.938 |
| asr.chunk | faster_whisper | 15.45 s | 9.31 s | 0.602 |
| asr.chunk | faster_whisper | 5.88 s | 8.02 s | 1.362 |
| asr.chunk | faster_whisper | 7.20 s | 7.21 s | 1.001 |
| asr.chunk | faster_whisper | 8.09 s | 7.86 s | 0.972 |
| asr.chunk | faster_whisper | 11.80 s | 8.29 s | 0.702 |
| asr.chunk | faster_whisper | 7.48 s | 8.08 s | 1.080 |
| asr.chunk | faster_whisper | 9.18 s | 8.20 s | 0.893 |
| asr.chunk | faster_whisper | 12.06 s | 9.35 s | 0.776 |
| asr.chunk | faster_whisper | 6.33 s | 7.48 s | 1.181 |
| asr.chunk | faster_whisper | 9.63 s | 8.76 s | 0.910 |
| asr.chunk | faster_whisper | 10.81 s | 8.68 s | 0.802 |
| asr.chunk | faster_whisper | 30.00 s | 14.96 s | 0.499 |
| asr.chunk | faster_whisper | 4.24 s | 6.69 s | 1.579 |
| asr.chunk | faster_whisper | 5.12 s | 7.44 s | 1.454 |
| asr.chunk | faster_whisper | 6.91 s | 7.41 s | 1.072 |
| asr.chunk | faster_whisper | 1.76 s | 6.08 s | 3.461 |
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
| load | ok | 1.92 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 52.78 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.86 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 15.51 s | 4,887 | 0 | 0 | 937 | — (not_supported) |
| **total** |  | 2 |  |  | 17.37 s | 4,899 | 0 | 0 | 943 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,449,502,208 B (2.28 GiB) → 3,103,420,416 B (2.89 GiB) |
| swap used | 17,395,712 B (0.02 GiB) → 20,840,448 B (0.02 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.03 s |
| telemetry buffer peak | 1,604 B |

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

- Top critical-path stages: asr_primary 662.60 s (57.1 %); language_detection 376.80 s (32.5 %); diarization_infer 52.79 s (4.5 %).
- Reprocessing ratio: 0.894.
- Cold loads: vad.model 1.50 s; diarization.load 1.92 s.
- Queue wait: 16.30 s.
- LLM latency share of wall: 1.5 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
