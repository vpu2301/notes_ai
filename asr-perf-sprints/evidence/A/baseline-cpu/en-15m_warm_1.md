# Diagnostics — recording bcae9f10-47a6-4fb0-ae8a-b4271f592c9d

Run `7f83b490-c6ba-46dd-8e2d-cece72f8300e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | bcae9f10-47a6-4fb0-ae8a-b4271f592c9d |
| processing_run_id | 7f83b490-c6ba-46dd-8e2d-cece72f8300e |
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
| processing_wall_seconds | 1275.49 s |
| rtf | 1.429 |
| speedup | 0.700 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.23 s | 0.0 % | -0.24 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.17 s |
| other | worker_job | 1 | ok | 1259.74 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.46 s | 0.0 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.49 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.49 s |
| vad | · vad.speech_runs | 1 | ok | 15.61 s | 1.2 % | +0.49 s |
| language_detection | · lid.recording | 1 | ok | 5.17 s | 0.4 % | +16.11 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 0.4 % | +21.28 s |
| language_detection | · lid.run | 1 | ok | 4.86 s | 0.4 % | +26.21 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 0.4 % | +31.08 s |
| language_detection | · lid.run | 1 | ok | 4.99 s | 0.4 % | +36.01 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 0.4 % | +41.01 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 0.4 % | +46.11 s |
| language_detection | · lid.run | 1 | ok | 5.00 s | 0.4 % | +51.19 s |
| language_detection | · lid.run | 1 | ok | 5.11 s | 0.4 % | +56.19 s |
| language_detection | · lid.run | 1 | ok | 5.31 s | 0.4 % | +61.30 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 0.4 % | +66.61 s |
| language_detection | · lid.run | 1 | ok | 5.15 s | 0.4 % | +71.88 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 0.4 % | +77.03 s |
| language_detection | · lid.run | 1 | ok | 5.21 s | 0.4 % | +82.28 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 0.4 % | +87.49 s |
| language_detection | · lid.run | 1 | ok | 5.34 s | 0.4 % | +92.72 s |
| language_detection | · lid.run | 1 | ok | 5.83 s | 0.5 % | +98.06 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +103.90 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +109.38 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +114.71 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 0.4 % | +120.19 s |
| language_detection | · lid.run | 1 | ok | 6.74 s | 0.5 % | +125.70 s |
| language_detection | · lid.run | 1 | ok | 5.48 s | 0.4 % | +132.44 s |
| language_detection | · lid.run | 1 | ok | 5.53 s | 0.4 % | +137.92 s |
| language_detection | · lid.run | 1 | ok | 5.70 s | 0.4 % | +143.45 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 0.4 % | +149.16 s |
| language_detection | · lid.run | 1 | ok | 5.85 s | 0.5 % | +154.71 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 0.4 % | +160.56 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +166.25 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +171.91 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.4 % | +177.44 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +183.02 s |
| language_detection | · lid.run | 1 | ok | 6.08 s | 0.5 % | +188.53 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.4 % | +194.62 s |
| language_detection | · lid.run | 1 | ok | 5.42 s | 0.4 % | +200.20 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +205.63 s |
| language_detection | · lid.run | 1 | ok | 5.58 s | 0.4 % | +211.19 s |
| language_detection | · lid.run | 1 | ok | 5.82 s | 0.5 % | +216.77 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +222.59 s |
| language_detection | · lid.run | 1 | ok | 5.75 s | 0.5 % | +228.21 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 0.4 % | +233.97 s |
| language_detection | · lid.run | 1 | ok | 5.45 s | 0.4 % | +239.66 s |
| language_detection | · lid.run | 1 | ok | 6.40 s | 0.5 % | +245.12 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 0.5 % | +251.52 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 0.4 % | +257.26 s |
| language_detection | · lid.run | 1 | ok | 5.42 s | 0.4 % | +262.76 s |
| language_detection | · lid.run | 1 | ok | 5.59 s | 0.4 % | +268.18 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +273.77 s |
| language_detection | · lid.run | 1 | ok | 5.84 s | 0.5 % | +279.30 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +285.14 s |
| language_detection | · lid.run | 1 | ok | 5.42 s | 0.4 % | +290.77 s |
| language_detection | · lid.run | 1 | ok | 5.65 s | 0.4 % | +296.19 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +301.83 s |
| language_detection | · lid.run | 1 | ok | 5.62 s | 0.4 % | +307.30 s |
| language_detection | · lid.run | 1 | ok | 5.55 s | 0.4 % | +312.92 s |
| language_detection | · lid.run | 1 | ok | 5.57 s | 0.4 % | +318.47 s |
| language_detection | · lid.run | 1 | ok | 5.72 s | 0.4 % | +324.04 s |
| language_detection | · lid.run | 1 | ok | 5.52 s | 0.4 % | +329.77 s |
| language_detection | · lid.run | 1 | ok | 5.42 s | 0.4 % | +335.28 s |
| language_detection | · lid.run | 1 | ok | 5.89 s | 0.5 % | +340.71 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +346.60 s |
| language_detection | · lid.run | 1 | ok | 5.47 s | 0.4 % | +352.27 s |
| language_detection | · lid.run | 1 | ok | 5.63 s | 0.4 % | +357.74 s |
| language_detection | · lid.run | 1 | ok | 5.69 s | 0.4 % | +363.37 s |
| language_detection | · lid.run | 1 | ok | 6.54 s | 0.5 % | +369.06 s |
| language_detection | · lid.run | 1 | ok | 5.67 s | 0.4 % | +375.61 s |
| language_detection | · lid.run | 1 | ok | 5.33 s | 0.4 % | +381.28 s |
| language_detection | · lid.run | 1 | ok | 5.51 s | 0.4 % | +386.61 s |
| language_detection | · lid.run | 1 | ok | 5.74 s | 0.5 % | +392.12 s |
| language_detection | · lid.run | 1 | ok | 5.60 s | 0.4 % | +397.86 s |
| language_detection | · lid.run | 1 | ok | 6.42 s | 0.5 % | +403.46 s |
| language_detection | · lid.run | 1 | ok | 5.54 s | 0.4 % | +409.89 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 0.5 % | +415.43 s |
| language_detection | · lid.run | 1 | ok | 5.56 s | 0.4 % | +421.21 s |
| language_detection | · lid.run | 1 | ok | 5.99 s | 0.5 % | +426.78 s |
| language_detection | · lid.run | 1 | ok | 5.50 s | 0.4 % | +432.78 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.5 % | +438.28 s |
| language_detection | · lid.run | 1 | ok | 5.66 s | 0.4 % | +444.05 s |
| language_detection | · lid.run | 1 | ok | 5.77 s | 0.5 % | +449.72 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 748.52 s | 58.7 % | +455.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.38 s | 0.8 % | +455.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.25 s | 0.7 % | +465.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.69 s | 0.6 % | +475.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.27 s | 0.9 % | +482.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.97 s | 0.6 % | +494.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.22 s | 0.7 % | +502.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.41 s | 0.7 % | +511.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.45 s | 0.7 % | +519.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.87 s | 0.7 % | +529.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.76 s | 0.8 % | +538.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.88 s | 0.6 % | +547.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.84 s | 0.8 % | +555.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.94 s | 0.7 % | +565.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.23 s | 0.6 % | +574.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.37 s | 1.1 % | +582.73 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.11 s | 0.9 % | +597.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.90 s | 0.7 % | +608.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.79 s | 0.7 % | +617.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.82 s | 0.5 % | +625.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.99 s | 1.0 % | +632.75 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.65 s | 0.8 % | +645.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.57 s | 0.5 % | +656.40 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.29 s | 0.7 % | +662.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.40 s | 0.7 % | +672.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.24 s | 0.8 % | +680.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.03 s | 0.7 % | +690.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.82 s | 0.8 % | +699.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.49 s | 0.7 % | +709.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.50 s | 0.8 % | +718.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.89 s | 0.9 % | +728.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.11 s | 0.8 % | +739.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.17 s | 0.8 % | +749.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.10 s | 0.6 % | +759.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.87 s | 0.5 % | +768.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.03 s | 0.8 % | +774.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.05 s | 0.7 % | +785.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.79 s | 0.8 % | +794.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.54 s | 0.7 % | +803.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.79 s | 1.0 % | +812.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.45 s | 0.7 % | +825.19 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.58 s | 0.7 % | +833.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.73 s | 0.8 % | +842.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.46 s | 0.7 % | +852.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.64 s | 0.6 % | +861.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.48 s | 0.7 % | +869.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.36 s | 0.6 % | +878.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.00 s | 0.7 % | +885.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 0.7 % | +894.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.00 s | 0.6 % | +903.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.34 s | 0.7 % | +911.83 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.81 s | 0.6 % | +920.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.26 s | 0.6 % | +927.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.77 s | 0.6 % | +936.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.19 s | 0.6 % | +944.02 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.02 s | 0.8 % | +951.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.14 s | 0.6 % | +961.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.09 s | 0.6 % | +969.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.85 s | 0.8 % | +976.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.43 s | 0.7 % | +986.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.42 s | 0.7 % | +995.78 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.17 s | 0.8 % | +1004.20 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 0.6 % | +1014.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.18 s | 0.8 % | +1022.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.44 s | 0.7 % | +1032.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.38 s | 0.7 % | +1040.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.67 s | 0.8 % | +1049.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.37 s | 0.7 % | +1059.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.72 s | 0.6 % | +1067.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 0.6 % | +1075.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.48 s | 0.7 % | +1083.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.66 s | 0.8 % | +1092.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 0.7 % | +1102.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.67 s | 0.8 % | +1111.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.86 s | 0.7 % | +1120.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.99 s | 0.8 % | +1129.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.00 s | 0.7 % | +1139.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.00 s | 1.3 % | +1148.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.78 s | 0.6 % | +1165.82 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.87 s | 0.6 % | +1173.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.75 s | 0.7 % | +1181.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.89 s | 0.5 % | +1190.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.88 s | 0.5 % | +1197.13 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +1204.01 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +1204.04 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +1204.14 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +1204.14 s |
| diarization_infer | · diarization.infer | 1 | ok | 55.35 s | 4.3 % | +1204.14 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.20 s | 0.0 % | +1259.49 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +1259.69 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +1259.69 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.76 s |
| queue | · asr.queue_wait | 1 | ok | 1259.76 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.77 s |
| queue | · asr.queue_wait | 1 | ok | 1259.76 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.77 s |
| queue | · asr.queue_wait | 1 | ok | 1259.76 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.77 s |
| queue | · asr.queue_wait | 1 | ok | 1259.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.78 s |
| queue | · asr.queue_wait | 1 | ok | 1259.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.78 s |
| queue | · asr.queue_wait | 1 | ok | 1259.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.78 s |
| queue | · asr.queue_wait | 1 | ok | 1259.77 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.78 s |
| queue | · asr.queue_wait | 1 | ok | 1259.78 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.79 s |
| queue | · asr.queue_wait | 1 | ok | 1259.78 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.79 s |
| queue | · asr.queue_wait | 1 | ok | 1259.78 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.79 s |
| queue | · asr.queue_wait | 1 | ok | 1259.79 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.80 s |
| queue | · asr.queue_wait | 1 | ok | 1259.79 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.80 s |
| queue | · asr.queue_wait | 1 | ok | 1259.80 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.81 s |
| queue | · asr.queue_wait | 1 | ok | 1259.80 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.81 s |
| queue | · asr.queue_wait | 1 | ok | 1259.80 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.81 s |
| queue | · asr.queue_wait | 1 | ok | 1259.81 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.82 s |
| queue | · asr.queue_wait | 1 | ok | 1259.81 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.82 s |
| queue | · asr.queue_wait | 1 | ok | 1259.81 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +1259.82 s |
| queue | · asr.queue_wait | 1 | ok | 1259.82 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.80 s | 0.1 % | +1261.77 s |
| other | notes.generate | 1 | ok | 12.92 s | — | +1262.58 s |
| llm_call | · llm.note_write | 1 | ok | 12.78 s | 1.0 % | +1262.64 s |

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
| lid.recording | 90.00 s | 5.17 s | en | en 0.998, es 0.000, ja 0.000 |
| lid.run | 15.39 s | 4.93 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 8.73 s | 4.86 s | en | en 0.983, ja 0.004, cy 0.002 |
| lid.run | 4.28 s | 4.93 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 16.38 s | 4.99 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 4.54 s | 5.10 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 13.53 s | 5.08 s | en | en 0.990, nn 0.003, cy 0.002 |
| lid.run | 8.12 s | 5.00 s | en | en 0.996, ja 0.001, pt 0.001 |
| lid.run | 10.59 s | 5.11 s | en | en 0.993, cy 0.002, nn 0.001 |
| lid.run | 7.90 s | 5.31 s | en | en 0.994, ja 0.002, es 0.001 |
| lid.run | 13.28 s | 5.26 s | en | en 0.981, cy 0.006, nn 0.004 |
| lid.run | 4.48 s | 5.15 s | en | en 0.982, la 0.004, ro 0.002 |
| lid.run | 13.12 s | 5.25 s | en | en 0.971, nn 0.008, cy 0.006 |
| lid.run | 7.48 s | 5.21 s | en | en 0.992, ja 0.002, cy 0.001 |
| lid.run | 6.24 s | 5.23 s | en | en 0.995, ja 0.001, cy 0.001 |
| lid.run | 28.38 s | 5.34 s | en | en 0.994, es 0.001, cy 0.001 |
| lid.run | 16.28 s | 5.83 s | en | en 0.991, ja 0.002, es 0.001 |
| lid.run | 7.04 s | 5.48 s | en | en 0.979, cy 0.006, nn 0.006 |
| lid.run | 9.63 s | 5.33 s | en | en 0.985, ja 0.002, ko 0.002 |
| lid.run | 2.49 s | 5.48 s | en | en 0.994, ja 0.001, cy 0.001 |
| lid.run | 24.16 s | 5.50 s | en | en 0.998, es 0.000, ru 0.000 |
| lid.run | 16.64 s | 6.74 s | en | en 0.997, cy 0.001, nn 0.001 |
| lid.run | 11.71 s | 5.48 s | en | en 0.990, la 0.003, nn 0.002 |
| lid.run | 6.46 s | 5.53 s | en | en 0.962, nn 0.008, la 0.007 |
| lid.run | 15.71 s | 5.70 s | en | en 0.995, nn 0.001, la 0.001 |
| lid.run | 8.73 s | 5.55 s | en | en 0.981, fi 0.004, nn 0.003 |
| lid.run | 13.47 s | 5.85 s | en | en 0.992, la 0.002, nn 0.001 |
| lid.run | 6.84 s | 5.69 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 17.82 s | 5.66 s | en | en 0.996, cy 0.001, la 0.001 |
| lid.run | 11.61 s | 5.52 s | en | en 0.983, ja 0.003, nn 0.002 |
| lid.run | 11.10 s | 5.58 s | en | en 0.994, ja 0.001, es 0.001 |
| lid.run | 12.41 s | 5.51 s | en | en 0.985, nn 0.004, la 0.003 |
| lid.run | 6.24 s | 6.08 s | en | en 0.974, ja 0.003, nn 0.003 |
| lid.run | 13.85 s | 5.58 s | en | en 0.973, nn 0.007, cy 0.004 |
| lid.run | 12.44 s | 5.42 s | en | en 0.997, la 0.001, nn 0.000 |
| lid.run | 10.84 s | 5.56 s | en | en 0.995, ja 0.002, es 0.001 |
| lid.run | 8.96 s | 5.58 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 20.76 s | 5.82 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 5.98 s | 5.62 s | en | en 0.990, ja 0.003, cy 0.001 |
| lid.run | 7.77 s | 5.75 s | en | en 0.970, nn 0.008, cy 0.005 |
| lid.run | 11.87 s | 5.69 s | en | en 0.997, ja 0.001, es 0.000 |
| lid.run | 4.48 s | 5.45 s | en | en 0.992, ja 0.001, nn 0.001 |
| lid.run | 5.53 s | 6.40 s | en | en 0.998, cy 0.000, ja 0.000 |
| lid.run | 11.64 s | 5.74 s | en | en 0.991, ja 0.001, es 0.001 |
| lid.run | 3.00 s | 5.50 s | en | en 0.922, cy 0.031, nn 0.011 |
| lid.run | 11.39 s | 5.42 s | en | en 0.995, es 0.001, cy 0.001 |
| lid.run | 11.77 s | 5.59 s | en | en 0.991, nn 0.003, la 0.001 |
| lid.run | 4.48 s | 5.52 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 8.64 s | 5.84 s | en | en 0.993, ja 0.001, ru 0.001 |
| lid.run | 6.01 s | 5.63 s | en | en 0.959, nn 0.013, cy 0.007 |
| lid.run | 8.03 s | 5.42 s | en | en 0.998, cy 0.001, ja 0.000 |
| lid.run | 2.56 s | 5.65 s | en | en 0.951, cy 0.007, nn 0.007 |
| lid.run | 2.49 s | 5.47 s | en | en 0.992, ja 0.002, es 0.001 |
| lid.run | 13.44 s | 5.62 s | en | en 0.996, cy 0.001, nn 0.001 |
| lid.run | 7.58 s | 5.55 s | en | en 0.974, cy 0.005, ro 0.002 |
| lid.run | 2.68 s | 5.57 s | en | en 0.988, la 0.003, cy 0.002 |
| lid.run | 8.83 s | 5.72 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 14.14 s | 5.52 s | en | en 0.997, nn 0.001, cy 0.000 |
| lid.run | 8.25 s | 5.42 s | en | en 0.972, nn 0.005, cy 0.005 |
| lid.run | 17.34 s | 5.89 s | en | en 0.997, la 0.001, nn 0.001 |
| lid.run | 6.24 s | 5.67 s | en | en 0.995, cy 0.001, ja 0.001 |
| lid.run | 13.85 s | 5.47 s | en | en 0.994, la 0.002, nn 0.001 |
| lid.run | 6.97 s | 5.63 s | en | en 0.998, ja 0.001, cy 0.000 |
| lid.run | 8.48 s | 5.69 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 15.45 s | 6.54 s | en | en 0.982, la 0.004, nn 0.004 |
| lid.run | 5.88 s | 5.67 s | en | en 0.997, ja 0.001, cy 0.000 |
| lid.run | 7.20 s | 5.33 s | en | en 0.984, cy 0.003, nn 0.003 |
| lid.run | 8.09 s | 5.51 s | en | en 0.990, ja 0.001, cy 0.001 |
| lid.run | 11.80 s | 5.74 s | en | en 0.989, nn 0.002, la 0.002 |
| lid.run | 7.48 s | 5.60 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 9.18 s | 6.42 s | en | en 0.990, ja 0.002, cy 0.002 |
| lid.run | 12.06 s | 5.54 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 6.33 s | 5.78 s | en | en 0.973, cy 0.007, nn 0.004 |
| lid.run | 9.63 s | 5.56 s | en | en 0.999, ja 0.000, es 0.000 |
| lid.run | 10.81 s | 5.99 s | en | en 0.994, nn 0.001, la 0.001 |
| lid.run | 30.00 s | 5.50 s | en | en 1.000, es 0.000, ja 0.000 |
| lid.run | 4.24 s | 5.77 s | en | en 0.994, ja 0.002, cy 0.001 |
| lid.run | 5.12 s | 5.66 s | en | en 0.971, nn 0.009, cy 0.006 |
| lid.run | 6.91 s | 5.77 s | en | en 0.998, ja 0.001, cy 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 15.39 s | 10.38 s | 0.674 |
| asr.chunk | faster_whisper | 8.73 s | 9.25 s | 1.059 |
| asr.chunk | faster_whisper | 4.28 s | 7.69 s | 1.796 |
| asr.chunk | faster_whisper | 16.38 s | 11.27 s | 0.688 |
| asr.chunk | faster_whisper | 4.54 s | 7.97 s | 1.756 |
| asr.chunk | faster_whisper | 13.53 s | 9.22 s | 0.682 |
| asr.chunk | faster_whisper | 8.12 s | 8.41 s | 1.036 |
| asr.chunk | faster_whisper | 10.59 s | 9.45 s | 0.893 |
| asr.chunk | faster_whisper | 7.90 s | 8.87 s | 1.123 |
| asr.chunk | faster_whisper | 13.28 s | 9.76 s | 0.735 |
| asr.chunk | faster_whisper | 4.48 s | 7.88 s | 1.760 |
| asr.chunk | faster_whisper | 13.12 s | 9.84 s | 0.750 |
| asr.chunk | faster_whisper | 7.48 s | 8.94 s | 1.195 |
| asr.chunk | faster_whisper | 6.24 s | 8.23 s | 1.320 |
| asr.chunk | faster_whisper | 28.38 s | 14.37 s | 0.506 |
| asr.chunk | faster_whisper | 16.28 s | 11.11 s | 0.683 |
| asr.chunk | faster_whisper | 7.04 s | 8.90 s | 1.264 |
| asr.chunk | faster_whisper | 9.63 s | 8.79 s | 0.913 |
| asr.chunk | faster_whisper | 2.49 s | 6.82 s | 2.737 |
| asr.chunk | faster_whisper | 24.16 s | 12.99 s | 0.538 |
| asr.chunk | faster_whisper | 16.64 s | 10.65 s | 0.640 |
| asr.chunk | faster_whisper | 1.28 s | 6.57 s | 5.148 |
| asr.chunk | faster_whisper | 11.71 s | 9.29 s | 0.794 |
| asr.chunk | faster_whisper | 6.46 s | 8.40 s | 1.301 |
| asr.chunk | faster_whisper | 15.71 s | 10.24 s | 0.652 |
| asr.chunk | faster_whisper | 8.73 s | 9.03 s | 1.034 |
| asr.chunk | faster_whisper | 13.47 s | 9.82 s | 0.729 |
| asr.chunk | faster_whisper | 6.84 s | 8.49 s | 1.241 |
| asr.chunk | faster_whisper | 17.82 s | 10.50 s | 0.589 |
| asr.chunk | faster_whisper | 11.61 s | 10.89 s | 0.938 |
| asr.chunk | faster_whisper | 11.10 s | 10.11 s | 0.911 |
| asr.chunk | faster_whisper | 12.41 s | 10.17 s | 0.819 |
| asr.chunk | faster_whisper | 6.24 s | 8.10 s | 1.299 |
| asr.chunk | faster_whisper | 1.82 s | 6.87 s | 3.776 |
| asr.chunk | faster_whisper | 13.85 s | 10.03 s | 0.724 |
| asr.chunk | faster_whisper | 12.44 s | 9.05 s | 0.727 |
| asr.chunk | faster_whisper | 10.84 s | 9.79 s | 0.903 |
| asr.chunk | faster_whisper | 8.96 s | 8.54 s | 0.953 |
| asr.chunk | faster_whisper | 20.76 s | 12.79 s | 0.616 |
| asr.chunk | faster_whisper | 5.98 s | 8.45 s | 1.414 |
| asr.chunk | faster_whisper | 7.77 s | 8.58 s | 1.104 |
| asr.chunk | faster_whisper | 11.87 s | 10.73 s | 0.904 |
| asr.chunk | faster_whisper | 4.48 s | 8.46 s | 1.889 |
| asr.chunk | faster_whisper | 5.53 s | 7.64 s | 1.380 |
| asr.chunk | faster_whisper | 11.64 s | 9.48 s | 0.814 |
| asr.chunk | faster_whisper | 3.00 s | 7.36 s | 2.449 |
| asr.chunk | faster_whisper | 11.39 s | 9.00 s | 0.791 |
| asr.chunk | faster_whisper | 11.77 s | 8.89 s | 0.755 |
| asr.chunk | faster_whisper | 4.48 s | 8.00 s | 1.787 |
| asr.chunk | faster_whisper | 8.64 s | 8.34 s | 0.966 |
| asr.chunk | faster_whisper | 6.01 s | 7.81 s | 1.299 |
| asr.chunk | faster_whisper | 8.03 s | 8.26 s | 1.029 |
| asr.chunk | faster_whisper | 2.56 s | 7.77 s | 3.038 |
| asr.chunk | faster_whisper | 2.49 s | 7.19 s | 2.887 |
| asr.chunk | faster_whisper | 13.44 s | 10.02 s | 0.746 |
| asr.chunk | faster_whisper | 7.58 s | 8.14 s | 1.074 |
| asr.chunk | faster_whisper | 2.68 s | 7.09 s | 2.641 |
| asr.chunk | faster_whisper | 8.83 s | 9.85 s | 1.115 |
| asr.chunk | faster_whisper | 14.14 s | 9.43 s | 0.667 |
| asr.chunk | faster_whisper | 8.25 s | 8.42 s | 1.020 |
| asr.chunk | faster_whisper | 17.34 s | 10.17 s | 0.587 |
| asr.chunk | faster_whisper | 6.24 s | 7.98 s | 1.280 |
| asr.chunk | faster_whisper | 13.85 s | 10.18 s | 0.735 |
| asr.chunk | faster_whisper | 6.97 s | 8.44 s | 1.210 |
| asr.chunk | faster_whisper | 8.48 s | 8.38 s | 0.988 |
| asr.chunk | faster_whisper | 15.45 s | 9.67 s | 0.626 |
| asr.chunk | faster_whisper | 5.88 s | 8.37 s | 1.422 |
| asr.chunk | faster_whisper | 7.20 s | 7.72 s | 1.073 |
| asr.chunk | faster_whisper | 8.09 s | 7.98 s | 0.986 |
| asr.chunk | faster_whisper | 11.80 s | 9.48 s | 0.803 |
| asr.chunk | faster_whisper | 7.48 s | 9.66 s | 1.291 |
| asr.chunk | faster_whisper | 9.18 s | 8.96 s | 0.976 |
| asr.chunk | faster_whisper | 12.06 s | 9.67 s | 0.802 |
| asr.chunk | faster_whisper | 6.33 s | 8.86 s | 1.399 |
| asr.chunk | faster_whisper | 9.63 s | 9.99 s | 1.038 |
| asr.chunk | faster_whisper | 10.81 s | 9.00 s | 0.833 |
| asr.chunk | faster_whisper | 30.00 s | 17.00 s | 0.567 |
| asr.chunk | faster_whisper | 4.24 s | 7.78 s | 1.837 |
| asr.chunk | faster_whisper | 5.12 s | 7.87 s | 1.537 |
| asr.chunk | faster_whisper | 6.91 s | 8.75 s | 1.267 |
| asr.chunk | faster_whisper | 1.76 s | 6.89 s | 3.923 |
| asr.chunk | faster_whisper | 1.98 s | 6.88 s | 3.476 |

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
| infer | ok | 55.34 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 4 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.80 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 12.78 s | 4,887 | 0 | 0 | 956 | — (not_supported) |
| **total** |  | 2 |  |  | 13.58 s | 4,899 | 0 | 0 | 962 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,403,512,320 B (2.24 GiB) → 2,416,951,296 B (2.25 GiB) |
| swap used | 211,910,656 B (0.20 GiB) → 293,998,592 B (0.27 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.01 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 2,029 B |

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

- Top critical-path stages: asr_primary 748.52 s (58.7 %); language_detection 439.18 s (34.4 %); diarization_infer 55.35 s (4.3 %).
- Reprocessing ratio: 0.894.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
