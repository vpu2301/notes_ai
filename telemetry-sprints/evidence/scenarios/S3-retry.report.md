# Diagnostics — recording 7a06a6e4-9a36-427c-8f34-5ec0e7d92b95

Run `17846383-6dcd-4ba8-90aa-51cdcb3e844e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7a06a6e4-9a36-427c-8f34-5ec0e7d92b95 |
| processing_run_id | 17846383-6dcd-4ba8-90aa-51cdcb3e844e |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 324.24 s |
| rtf | 2.702 |
| speedup | 0.370 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.32 s | 0.1 % | -0.33 s |
| capture_input | asr.submit.probe | 1 | ok | 0.14 s | 0.0 % | -0.26 s |
| other | worker_job | 1 | ok | 282.32 s | — | +0.04 s |
| queue | · asr.queue_wait | 1 | ok | 0.03 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.25 s | 0.1 % | +0.06 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.31 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.31 s |
| vad | · vad.speech_runs | 1 | ok | 4.83 s | 1.5 % | +0.32 s |
| language_detection | · lid.run | 1 | ok | 11.34 s | 3.5 % | +5.15 s |
| language_detection | · lid.run | 1 | ok | 11.77 s | 3.6 % | +16.49 s |
| language_detection | · lid.run | 1 | ok | 10.62 s | 3.3 % | +28.28 s |
| language_detection | · lid.run | 1 | ok | 9.99 s | 3.1 % | +38.91 s |
| language_detection | · lid.run | 1 | ok | 10.45 s | 3.2 % | +48.90 s |
| language_detection | · lid.run | 1 | ok | 10.60 s | 3.3 % | +59.37 s |
| language_detection | · lid.run | 1 | ok | 10.58 s | 3.3 % | +69.97 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 185.24 s | 57.1 % | +80.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.91 s | 8.6 % | +80.55 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.86 s | 5.5 % | +108.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.33 s | 6.9 % | +126.36 s |
| asr_primary | · · asr.chunk | 1 | ok | 49.09 s | 15.1 % | +148.70 s |
| asr_primary | · · asr.chunk | 1 | ok | 29.56 s | 9.1 % | +197.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 22.61 s | 7.0 % | +227.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.79 s | 4.9 % | +250.00 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +265.80 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +265.80 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +265.81 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +265.81 s |
| diarization_infer | · diarization.infer | 1 | ok | 16.46 s | 5.1 % | +265.81 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +282.27 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +282.28 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +282.28 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.39 s |
| queue | · asr.queue_wait | 1 | ok | 282.37 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.39 s |
| queue | · asr.queue_wait | 1 | ok | 282.38 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.40 s |
| queue | · asr.queue_wait | 1 | ok | 282.39 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +282.40 s |
| queue | · asr.queue_wait | 1 | ok | 282.39 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 8.22 s | 2.5 % | +304.58 s |
| other | notes.generate | 1 | ok | 11.44 s | — | +312.80 s |
| llm_call | · llm.note_write | 1 | error | 0.00 s | 0.0 % | +313.20 s |
| llm_call | · llm.note_write | 1 | ok | 9.94 s | 3.1 % | +314.21 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 115.72 s | 7 | 4.73 s | 18.81 s | 29.98 s |

### Language checks

Language checks: 7.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 11.34 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 11.77 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.62 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 9.99 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 10.45 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 10.60 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 10.58 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 27.91 s | 1.210 |
| asr.chunk | faster_whisper | 5.08 s | 17.86 s | 3.513 |
| asr.chunk | faster_whisper | 14.36 s | 22.33 s | 1.554 |
| asr.chunk | faster_whisper | 29.98 s | 49.09 s | 1.638 |
| asr.chunk | faster_whisper | 19.68 s | 29.56 s | 1.502 |
| asr.chunk | faster_whisper | 18.81 s | 22.61 s | 1.202 |
| asr.chunk | faster_whisper | 4.73 s | 15.79 s | 3.336 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 115.72 s |
| audio duration | 120.00 s |
| reprocessing ratio | 0.964 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 16.46 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.22 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | error | — (not_applicable) | 0.00 s | 1,205* | — | — | — | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 2 | ok | — (not_applicable) | 9.94 s | 1,085 | 0 | 0 | 335 | — (not_supported) |
| **total** |  | 3 |  |  | 18.15 s | 2,302 | 0 | 0 | 341 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again; estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,371,727,360 B (2.21 GiB) → 3,219,263,488 B (3.00 GiB) |
| swap used | 1,262,321,664 B (1.18 GiB) → 1,260,498,944 B (1.17 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.12 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,561 B |

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
  - llm.note_write: `finish_reason` (unavailable)
  - llm.note_write: `http_status` (unavailable)
  - llm.provider_probe: `error_subtype` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - note_write (attempt 1): `cached_input_tokens` (unavailable)
  - note_write (attempt 1): `completion_chars` (unavailable)
  - note_write (attempt 1): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 1): `model_load_seconds` (not_applicable)
  - note_write (attempt 1): `output_tokens` (unavailable)
  - note_write (attempt 1): `reasoning_tokens` (unavailable)
  - note_write (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - note_write (attempt 2): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 2): `model_load_seconds` (unavailable)
  - note_write (attempt 2): `time_to_first_token_seconds` (not_applicable)
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

- Top critical-path stages: asr_primary 185.25 s (57.1 %); language_detection 75.35 s (23.2 %); llm_call 18.16 s (5.6 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 0.03 s.
- LLM latency share of wall: 5.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
