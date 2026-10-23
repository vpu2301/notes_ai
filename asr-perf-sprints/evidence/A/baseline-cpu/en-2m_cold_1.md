# Diagnostics — recording 5c51c2f1-a5e7-4a69-b474-83177db95921

Run `ba38b1f0-1284-4bc1-979e-f8282f2a01e7` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 5c51c2f1-a5e7-4a69-b474-83177db95921 |
| processing_run_id | ba38b1f0-1284-4bc1-979e-f8282f2a01e7 |
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
| audio duration | 113.84 s |
| processing_wall_seconds | 203.51 s |
| rtf | 1.788 |
| speedup | 0.559 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.11 s | 0.1 % | -0.12 s |
| capture_input | asr.submit.probe | 1 | ok | 0.08 s | 0.0 % | -0.10 s |
| other | worker_job | 1 | ok | 186.93 s | — | +10.57 s |
| queue | · asr.queue_wait | 1 | ok | 10.57 s | 5.2 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.26 s | 0.1 % | +10.58 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +10.84 s |
| model_init | · vad.model | 1 | ok | 1.34 s | 0.7 % | +10.84 s |
| vad | · vad.speech_runs | 1 | ok | 3.84 s | 1.9 % | +12.18 s |
| language_detection | · lid.recording | 1 | ok | 4.84 s | 2.4 % | +16.02 s |
| language_detection | · lid.run | 1 | ok | 4.46 s | 2.2 % | +20.86 s |
| language_detection | · lid.run | 1 | ok | 4.52 s | 2.2 % | +25.32 s |
| language_detection | · lid.run | 1 | ok | 4.49 s | 2.2 % | +29.84 s |
| language_detection | · lid.run | 1 | ok | 4.56 s | 2.2 % | +34.34 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.4 % | +38.91 s |
| language_detection | · lid.run | 1 | ok | 5.78 s | 2.8 % | +43.76 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 2.6 % | +49.55 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 2.3 % | +54.84 s |
| language_detection | · lid.run | 1 | ok | 4.87 s | 2.4 % | +59.51 s |
| language_detection | · lid.run | 1 | ok | 4.76 s | 2.3 % | +64.38 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 2.5 % | +69.14 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 2.4 % | +74.18 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 2.2 % | +79.16 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 2.4 % | +83.73 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 99.18 s | 48.7 % | +88.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.90 s | 3.4 % | +88.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.80 s | 3.3 % | +95.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.93 s | 3.4 % | +102.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.12 s | 3.5 % | +109.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.10 s | 3.5 % | +116.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.22 s | 3.5 % | +123.39 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.56 s | 3.7 % | +130.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.53 s | 3.2 % | +138.17 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.52 s | 3.2 % | +144.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.59 s | 3.2 % | +151.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.69 s | 4.8 % | +157.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.50 s | 3.7 % | +167.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.72 s | 3.3 % | +175.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.96 s | 2.9 % | +181.73 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +187.70 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +187.71 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +187.72 s |
| diarization_load | · diarization.load | 1 | ok | 2.13 s | 1.0 % | +187.72 s |
| diarization_infer | · diarization.infer | 1 | ok | 7.63 s | 3.7 % | +189.85 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +197.47 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +197.47 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +197.48 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +197.51 s |
| queue | · asr.queue_wait | 1 | ok | 197.51 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +197.52 s |
| queue | · asr.queue_wait | 1 | ok | 197.51 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +197.52 s |
| queue | · asr.queue_wait | 1 | ok | 197.52 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.62 s | 0.3 % | +198.65 s |
| other | notes.generate | 1 | ok | 4.23 s | — | +199.28 s |
| llm_call | · llm.note_write | 1 | ok | 4.14 s | 2.0 % | +199.33 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 100.83 s | 14 | 2.83 s | 6.81 s | 17.12 s |

### Language checks

Language checks: 15.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 4.84 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 4.46 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 4.52 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 4.49 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 4.56 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 4.85 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 5.78 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 5.29 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 4.66 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 4.87 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 4.76 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 5.03 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 4.98 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 4.57 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 4.78 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 6.90 s | 1.073 |
| asr.chunk | faster_whisper | 7.23 s | 6.80 s | 0.941 |
| asr.chunk | faster_whisper | 6.88 s | 6.93 s | 1.008 |
| asr.chunk | faster_whisper | 6.75 s | 7.12 s | 1.055 |
| asr.chunk | faster_whisper | 7.26 s | 7.10 s | 0.978 |
| asr.chunk | faster_whisper | 7.93 s | 7.22 s | 0.910 |
| asr.chunk | faster_whisper | 8.86 s | 7.56 s | 0.854 |
| asr.chunk | faster_whisper | 5.31 s | 6.53 s | 1.230 |
| asr.chunk | faster_whisper | 5.34 s | 6.52 s | 1.221 |
| asr.chunk | faster_whisper | 5.79 s | 6.59 s | 1.138 |
| asr.chunk | faster_whisper | 17.12 s | 9.69 s | 0.566 |
| asr.chunk | faster_whisper | 8.38 s | 7.50 s | 0.895 |
| asr.chunk | faster_whisper | 4.73 s | 6.72 s | 1.420 |
| asr.chunk | faster_whisper | 2.83 s | 5.96 s | 2.103 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 100.83 s |
| audio duration | 113.84 s |
| reprocessing ratio | 0.886 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 2.13 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 7.63 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.14 s | 1,764 | 0 | 0 | 250 | — (not_supported) |
| **total** |  | 2 |  |  | 4.76 s | 1,776 | 0 | 0 | 256 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,940,544 B (2.29 GiB) → 3,097,808,896 B (2.89 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.04 → some_avg10=0.68 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,173 B |

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

- Top critical-path stages: asr_primary 99.18 s (48.7 %); language_detection 72.47 s (35.6 %); queue 10.57 s (5.2 %).
- Reprocessing ratio: 0.886.
- Cold loads: vad.model 1.34 s; diarization.load 2.13 s.
- Queue wait: 10.57 s.
- LLM latency share of wall: 2.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
