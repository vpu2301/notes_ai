# Diagnostics — recording 784e1fa5-ed16-4036-b7c9-8255f5b41419

Run `05dbdc98-93f1-4296-b125-78f04f941e98` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 784e1fa5-ed16-4036-b7c9-8255f5b41419 |
| processing_run_id | 05dbdc98-93f1-4296-b125-78f04f941e98 |
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
| audio duration | 178.25 s |
| processing_wall_seconds | 560.87 s |
| rtf | 3.146 |
| speedup | 0.318 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.29 s | 0.1 % | -0.29 s |
| capture_input | asr.submit.probe | 1 | ok | 0.16 s | 0.0 % | -0.23 s |
| other | worker_job | 1 | ok | 551.65 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.31 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.34 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.34 s |
| vad | · vad.speech_runs | 1 | ok | 7.96 s | 1.4 % | +0.34 s |
| language_detection | · lid.recording | 1 | ok | 9.49 s | 1.7 % | +8.31 s |
| language_detection | · lid.run | 1 | ok | 10.10 s | 1.8 % | +17.80 s |
| language_detection | · lid.run | 1 | ok | 10.41 s | 1.9 % | +27.90 s |
| language_detection | · lid.run | 1 | ok | 10.05 s | 1.8 % | +38.32 s |
| language_detection | · lid.run | 1 | ok | 9.11 s | 1.6 % | +48.38 s |
| language_detection | · lid.run | 1 | ok | 9.01 s | 1.6 % | +57.49 s |
| language_detection | · lid.run | 1 | ok | 8.78 s | 1.6 % | +66.51 s |
| language_detection | · lid.run | 1 | ok | 10.18 s | 1.8 % | +75.29 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 1.6 % | +85.48 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 1.7 % | +94.70 s |
| language_detection | · lid.run | 1 | ok | 9.18 s | 1.6 % | +104.43 s |
| language_detection | · lid.run | 1 | ok | 10.41 s | 1.9 % | +113.61 s |
| language_detection | · lid.run | 1 | ok | 12.20 s | 2.2 % | +124.04 s |
| language_detection | · lid.run | 1 | ok | 10.48 s | 1.9 % | +136.25 s |
| language_detection | · lid.run | 1 | ok | 10.10 s | 1.8 % | +146.73 s |
| language_detection | · lid.run | 1 | ok | 8.97 s | 1.6 % | +156.84 s |
| language_detection | · lid.run | 1 | ok | 9.36 s | 1.7 % | +165.81 s |
| language_detection | · lid.run | 1 | ok | 8.80 s | 1.6 % | +175.18 s |
| language_detection | · lid.run | 1 | ok | 10.74 s | 1.9 % | +183.98 s |
| language_detection | · lid.run | 1 | ok | 9.27 s | 1.7 % | +194.73 s |
| language_detection | · lid.run | 1 | ok | 9.20 s | 1.6 % | +204.01 s |
| language_detection | · lid.run | 1 | ok | 10.56 s | 1.9 % | +213.21 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 303.44 s | 54.1 % | +223.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.57 s | 2.4 % | +223.77 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.73 s | 2.4 % | +237.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.62 s | 2.3 % | +251.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.33 s | 2.4 % | +263.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.94 s | 2.3 % | +277.10 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.86 s | 2.5 % | +290.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.62 s | 2.4 % | +303.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.49 s | 2.2 % | +317.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.67 s | 2.3 % | +330.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.45 s | 2.2 % | +342.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.75 s | 2.1 % | +355.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.76 s | 2.3 % | +366.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.02 s | 2.1 % | +379.67 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.81 s | 1.9 % | +391.69 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.11 s | 3.1 % | +402.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 19.19 s | 3.4 % | +419.64 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.44 s | 2.9 % | +438.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.26 s | 2.9 % | +455.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.71 s | 2.8 % | +471.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.54 s | 2.6 % | +487.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.08 s | 2.3 % | +501.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.28 s | 2.2 % | +514.92 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +527.20 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +527.21 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +527.22 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +527.22 s |
| diarization_infer | · diarization.infer | 1 | ok | 24.38 s | 4.3 % | +527.22 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +551.60 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +551.61 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +551.61 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.68 s |
| queue | · asr.queue_wait | 1 | ok | 551.67 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.68 s |
| queue | · asr.queue_wait | 1 | ok | 551.68 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.69 s |
| queue | · asr.queue_wait | 1 | ok | 551.68 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.69 s |
| queue | · asr.queue_wait | 1 | ok | 551.69 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.70 s |
| queue | · asr.queue_wait | 1 | ok | 551.69 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.70 s |
| queue | · asr.queue_wait | 1 | ok | 551.69 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.70 s |
| queue | · asr.queue_wait | 1 | ok | 551.70 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +551.71 s |
| queue | · asr.queue_wait | 1 | ok | 551.70 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.62 s | 0.1 % | +553.92 s |
| other | notes.generate | 1 | ok | 6.32 s | — | +554.54 s |
| llm_call | · llm.note_write | 1 | ok | 6.21 s | 1.1 % | +554.60 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 149.22 s | 22 | 1.05 s | 6.84 s | 11.64 s |

### Language checks

Language checks: 22.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 9.49 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 10.10 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 10.41 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 10.05 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 9.11 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 9.01 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 8.78 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 10.18 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 9.22 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 9.71 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 9.18 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 10.41 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 12.20 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 10.48 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 10.10 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 8.97 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 9.36 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 8.80 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 10.74 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 9.27 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 9.20 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 10.56 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 13.57 s | 1.920 |
| asr.chunk | faster_whisper | 7.71 s | 13.73 s | 1.781 |
| asr.chunk | faster_whisper | 6.62 s | 12.62 s | 1.907 |
| asr.chunk | faster_whisper | 7.71 s | 13.33 s | 1.729 |
| asr.chunk | faster_whisper | 6.24 s | 12.94 s | 2.075 |
| asr.chunk | faster_whisper | 7.07 s | 13.86 s | 1.962 |
| asr.chunk | faster_whisper | 7.16 s | 13.62 s | 1.901 |
| asr.chunk | faster_whisper | 6.56 s | 12.49 s | 1.906 |
| asr.chunk | faster_whisper | 6.24 s | 12.67 s | 2.032 |
| asr.chunk | faster_whisper | 5.88 s | 12.44 s | 2.115 |
| asr.chunk | faster_whisper | 4.92 s | 11.75 s | 2.385 |
| asr.chunk | faster_whisper | 6.43 s | 12.76 s | 1.985 |
| asr.chunk | faster_whisper | 4.48 s | 12.02 s | 2.685 |
| asr.chunk | faster_whisper | 1.05 s | 10.80 s | 10.271 |
| asr.chunk | faster_whisper | 7.90 s | 17.11 s | 2.166 |
| asr.chunk | faster_whisper | 10.46 s | 19.19 s | 1.835 |
| asr.chunk | faster_whisper | 8.41 s | 16.44 s | 1.954 |
| asr.chunk | faster_whisper | 9.66 s | 16.26 s | 1.683 |
| asr.chunk | faster_whisper | 11.64 s | 15.71 s | 1.349 |
| asr.chunk | faster_whisper | 7.45 s | 14.54 s | 1.951 |
| asr.chunk | faster_whisper | 5.88 s | 13.08 s | 2.224 |
| asr.chunk | faster_whisper | 2.68 s | 12.28 s | 4.574 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 149.22 s |
| audio duration | 178.25 s |
| reprocessing ratio | 0.837 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 24.38 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.21 s | 2,071 | 0 | 0 | 442 | — (not_supported) |
| **total** |  | 2 |  |  | 6.83 s | 2,083 | 0 | 0 | 448 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,413,563,904 B (2.25 GiB) → 2,419,965,952 B (2.25 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.04 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,649 B |

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

- Top critical-path stages: asr_primary 303.44 s (54.1 %); language_detection 215.32 s (38.4 %); diarization_infer 24.38 s (4.3 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.2 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
