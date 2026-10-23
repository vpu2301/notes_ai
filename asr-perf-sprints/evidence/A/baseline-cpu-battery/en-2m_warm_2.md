# Diagnostics — recording 4a70f0f6-a301-4dac-8290-784327b17a34

Run `5fdf3c4f-0021-48e6-8736-88cc4b5470df` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 4a70f0f6-a301-4dac-8290-784327b17a34 |
| processing_run_id | 5fdf3c4f-0021-48e6-8736-88cc4b5470df |
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
| processing_wall_seconds | 391.12 s |
| rtf | 3.436 |
| speedup | 0.291 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.0 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.10 s | 0.0 % | -0.14 s |
| other | worker_job | 1 | ok | 385.18 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.19 s | 0.0 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.20 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.20 s |
| vad | · vad.speech_runs | 1 | ok | 3.18 s | 0.8 % | +0.21 s |
| language_detection | · lid.recording | 1 | ok | 8.81 s | 2.3 % | +3.39 s |
| language_detection | · lid.run | 1 | ok | 8.53 s | 2.2 % | +12.21 s |
| language_detection | · lid.run | 1 | ok | 8.79 s | 2.2 % | +20.74 s |
| language_detection | · lid.run | 1 | ok | 8.67 s | 2.2 % | +29.54 s |
| language_detection | · lid.run | 1 | ok | 8.10 s | 2.1 % | +38.21 s |
| language_detection | · lid.run | 1 | ok | 9.23 s | 2.4 % | +46.31 s |
| language_detection | · lid.run | 1 | ok | 9.99 s | 2.6 % | +55.56 s |
| language_detection | · lid.run | 1 | ok | 10.01 s | 2.6 % | +65.58 s |
| language_detection | · lid.run | 1 | ok | 8.65 s | 2.2 % | +75.60 s |
| language_detection | · lid.run | 1 | ok | 8.63 s | 2.2 % | +84.26 s |
| language_detection | · lid.run | 1 | ok | 8.81 s | 2.3 % | +92.89 s |
| language_detection | · lid.run | 1 | ok | 8.88 s | 2.3 % | +101.70 s |
| language_detection | · lid.run | 1 | ok | 9.05 s | 2.3 % | +110.59 s |
| language_detection | · lid.run | 1 | ok | 10.16 s | 2.6 % | +119.65 s |
| language_detection | · lid.run | 1 | ok | 9.43 s | 2.4 % | +129.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 226.77 s | 58.0 % | +139.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.06 s | 3.9 % | +139.25 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.67 s | 3.8 % | +154.31 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.87 s | 3.8 % | +168.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.20 s | 4.1 % | +183.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.27 s | 4.7 % | +200.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.53 s | 4.5 % | +218.37 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.00 s | 5.1 % | +235.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.69 s | 4.0 % | +255.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.27 s | 3.6 % | +271.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.36 s | 3.7 % | +285.90 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.46 s | 6.0 % | +300.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.85 s | 4.1 % | +323.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.66 s | 3.5 % | +339.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.75 s | 3.3 % | +353.26 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +366.02 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +366.02 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +366.03 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +366.03 s |
| diarization_infer | · diarization.infer | 1 | ok | 19.08 s | 4.9 % | +366.03 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +385.11 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +385.12 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +385.12 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +385.20 s |
| queue | · asr.queue_wait | 1 | ok | 385.20 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +385.21 s |
| queue | · asr.queue_wait | 1 | ok | 385.20 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +385.22 s |
| queue | · asr.queue_wait | 1 | ok | 385.21 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +385.22 s |
| queue | · asr.queue_wait | 1 | ok | 385.22 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +385.23 s |
| queue | · asr.queue_wait | 1 | ok | 385.22 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.74 s | 0.2 % | +386.38 s |
| other | notes.generate | 1 | ok | 3.99 s | — | +387.13 s |
| llm_call | · llm.note_write | 1 | ok | 3.86 s | 1.0 % | +387.19 s |

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
| lid.recording | 90.00 s | 8.81 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 8.53 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 8.79 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 8.67 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 8.10 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 9.23 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 9.99 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 10.01 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 8.65 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 8.63 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 8.81 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 8.88 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 9.05 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 10.16 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 9.43 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 15.06 s | 2.343 |
| asr.chunk | faster_whisper | 7.23 s | 14.67 s | 2.030 |
| asr.chunk | faster_whisper | 6.88 s | 14.87 s | 2.163 |
| asr.chunk | faster_whisper | 6.75 s | 16.20 s | 2.401 |
| asr.chunk | faster_whisper | 7.26 s | 18.27 s | 2.516 |
| asr.chunk | faster_whisper | 7.93 s | 17.53 s | 2.210 |
| asr.chunk | faster_whisper | 8.86 s | 20.00 s | 2.258 |
| asr.chunk | faster_whisper | 5.31 s | 15.69 s | 2.955 |
| asr.chunk | faster_whisper | 5.34 s | 14.27 s | 2.672 |
| asr.chunk | faster_whisper | 5.79 s | 14.36 s | 2.480 |
| asr.chunk | faster_whisper | 17.12 s | 23.46 s | 1.371 |
| asr.chunk | faster_whisper | 8.38 s | 15.85 s | 1.891 |
| asr.chunk | faster_whisper | 4.73 s | 13.65 s | 2.886 |
| asr.chunk | faster_whisper | 2.83 s | 12.75 s | 4.499 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 19.08 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.74 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 3.86 s | 1,764 | 0 | 0 | 272 | — (not_supported) |
| **total** |  | 2 |  |  | 4.60 s | 1,776 | 0 | 0 | 278 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,974,531,584 B (2.77 GiB) → 3,029,524,480 B (2.82 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.03 s |
| telemetry buffer peak | 1,602 B |

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

- Top critical-path stages: asr_primary 226.77 s (58.0 %); language_detection 135.76 s (34.7 %); diarization_infer 19.08 s (4.9 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.2 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
