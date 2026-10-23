# Diagnostics — recording ed00ff59-14aa-4738-9e4c-af576d06839f

Run `6691d154-b63e-411e-a302-602511a2603c` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ed00ff59-14aa-4738-9e4c-af576d06839f |
| processing_run_id | 6691d154-b63e-411e-a302-602511a2603c |
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
| processing_wall_seconds | 206.38 s |
| rtf | 1.813 |
| speedup | 0.552 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.09 s | 0.0 % | -0.09 s |
| capture_input | asr.submit.probe | 1 | ok | 0.05 s | 0.0 % | -0.08 s |
| other | worker_job | 1 | ok | 199.26 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.12 s | 0.1 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.13 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.13 s |
| vad | · vad.speech_runs | 1 | ok | 1.86 s | 0.9 % | +0.14 s |
| language_detection | · lid.recording | 1 | ok | 5.64 s | 2.7 % | +2.00 s |
| language_detection | · lid.run | 1 | ok | 5.20 s | 2.5 % | +7.65 s |
| language_detection | · lid.run | 1 | ok | 5.26 s | 2.5 % | +12.85 s |
| language_detection | · lid.run | 1 | ok | 5.08 s | 2.5 % | +18.11 s |
| language_detection | · lid.run | 1 | ok | 5.13 s | 2.5 % | +23.19 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 2.4 % | +28.33 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 2.4 % | +33.35 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.5 % | +38.37 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 2.6 % | +43.46 s |
| language_detection | · lid.run | 1 | ok | 5.31 s | 2.6 % | +48.82 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 2.6 % | +54.13 s |
| language_detection | · lid.run | 1 | ok | 5.10 s | 2.5 % | +59.39 s |
| language_detection | · lid.run | 1 | ok | 5.09 s | 2.5 % | +64.50 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 2.5 % | +69.58 s |
| language_detection | · lid.run | 1 | ok | 5.27 s | 2.6 % | +74.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 110.86 s | 53.7 % | +80.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.66 s | 3.7 % | +80.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.56 s | 3.7 % | +87.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.47 s | 3.6 % | +95.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 4.0 % | +102.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.72 s | 4.2 % | +110.95 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.93 s | 3.8 % | +119.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.35 s | 4.0 % | +127.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.57 s | 3.7 % | +135.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.33 s | 3.6 % | +143.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.35 s | 3.6 % | +150.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.75 s | 5.2 % | +158.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.32 s | 4.0 % | +168.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.28 s | 3.5 % | +177.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.36 s | 3.1 % | +184.58 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +190.94 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +190.94 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +190.95 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +190.95 s |
| diarization_infer | · diarization.infer | 1 | ok | 8.26 s | 4.0 % | +190.95 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +199.21 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +199.21 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +199.22 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +199.28 s |
| queue | · asr.queue_wait | 1 | ok | 199.27 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +199.28 s |
| queue | · asr.queue_wait | 1 | ok | 199.28 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.92 s | 0.4 % | +200.06 s |
| other | notes.generate | 1 | ok | 5.40 s | — | +200.99 s |
| llm_call | · llm.note_write | 1 | ok | 5.32 s | 2.6 % | +201.04 s |

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
| lid.recording | 90.00 s | 5.64 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 5.20 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 5.26 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 5.08 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 5.13 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 5.02 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 5.02 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 5.09 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 5.36 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 5.31 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 5.27 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 5.10 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 5.09 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 5.23 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 5.27 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 7.66 s | 1.192 |
| asr.chunk | faster_whisper | 7.23 s | 7.56 s | 1.046 |
| asr.chunk | faster_whisper | 6.88 s | 7.47 s | 1.087 |
| asr.chunk | faster_whisper | 6.75 s | 8.16 s | 1.209 |
| asr.chunk | faster_whisper | 7.26 s | 8.72 s | 1.202 |
| asr.chunk | faster_whisper | 7.93 s | 7.93 s | 1.000 |
| asr.chunk | faster_whisper | 8.86 s | 8.35 s | 0.943 |
| asr.chunk | faster_whisper | 5.31 s | 7.57 s | 1.426 |
| asr.chunk | faster_whisper | 5.34 s | 7.33 s | 1.373 |
| asr.chunk | faster_whisper | 5.79 s | 7.35 s | 1.269 |
| asr.chunk | faster_whisper | 17.12 s | 10.75 s | 0.628 |
| asr.chunk | faster_whisper | 8.38 s | 8.32 s | 0.993 |
| asr.chunk | faster_whisper | 4.73 s | 7.28 s | 1.538 |
| asr.chunk | faster_whisper | 2.83 s | 6.36 s | 2.245 |

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
| infer | ok | 8.26 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.92 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 5.32 s | 1,764 | 0 | 0 | 316 | — (not_supported) |
| **total** |  | 2 |  |  | 6.24 s | 1,776 | 0 | 0 | 322 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,384,838,656 B (2.22 GiB) → 3,102,285,824 B (2.89 GiB) |
| swap used | 50,286,592 B (0.05 GiB) → 73,117,696 B (0.07 GiB) |
| memory pressure | some_avg10=0.03 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,599 B |

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

- Top critical-path stages: asr_primary 110.86 s (53.7 %); language_detection 78.05 s (37.8 %); diarization_infer 8.26 s (4.0 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 3.0 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
