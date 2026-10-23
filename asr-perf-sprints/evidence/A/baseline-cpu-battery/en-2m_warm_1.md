# Diagnostics — recording 3db8cdd2-beef-465d-aade-b36e56eb3493

Run `4371ac7a-8652-433c-ab58-58358b3577ff` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 3db8cdd2-beef-465d-aade-b36e56eb3493 |
| processing_run_id | 4371ac7a-8652-433c-ab58-58358b3577ff |
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
| processing_wall_seconds | 341.89 s |
| rtf | 3.003 |
| speedup | 0.333 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.26 s | 0.1 % | -0.26 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.17 s |
| other | worker_job | 1 | ok | 334.12 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.21 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| vad | · vad.speech_runs | 1 | ok | 3.70 s | 1.1 % | +0.24 s |
| language_detection | · lid.recording | 1 | ok | 8.82 s | 2.6 % | +3.94 s |
| language_detection | · lid.run | 1 | ok | 8.34 s | 2.4 % | +12.76 s |
| language_detection | · lid.run | 1 | ok | 8.43 s | 2.5 % | +21.10 s |
| language_detection | · lid.run | 1 | ok | 9.03 s | 2.6 % | +29.53 s |
| language_detection | · lid.run | 1 | ok | 8.53 s | 2.5 % | +38.57 s |
| language_detection | · lid.run | 1 | ok | 8.73 s | 2.6 % | +47.10 s |
| language_detection | · lid.run | 1 | ok | 9.97 s | 2.9 % | +55.84 s |
| language_detection | · lid.run | 1 | ok | 9.35 s | 2.7 % | +65.82 s |
| language_detection | · lid.run | 1 | ok | 8.78 s | 2.6 % | +75.17 s |
| language_detection | · lid.run | 1 | ok | 8.59 s | 2.5 % | +83.96 s |
| language_detection | · lid.run | 1 | ok | 8.58 s | 2.5 % | +92.55 s |
| language_detection | · lid.run | 1 | ok | 8.46 s | 2.5 % | +101.14 s |
| language_detection | · lid.run | 1 | ok | 8.97 s | 2.6 % | +109.60 s |
| language_detection | · lid.run | 1 | ok | 8.39 s | 2.5 % | +118.58 s |
| language_detection | · lid.run | 1 | ok | 9.51 s | 2.8 % | +126.97 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 184.07 s | 53.8 % | +136.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.97 s | 3.8 % | +136.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.71 s | 3.7 % | +149.47 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.10 s | 3.8 % | +162.18 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.13 s | 3.8 % | +175.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.70 s | 3.7 % | +188.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.84 s | 4.0 % | +201.12 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.03 s | 4.1 % | +214.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.76 s | 3.4 % | +229.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.49 s | 3.7 % | +240.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.35 s | 3.6 % | +253.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.36 s | 5.4 % | +265.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.16 s | 4.1 % | +283.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.24 s | 3.6 % | +298.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.15 s | 3.0 % | +310.40 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +320.55 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +320.56 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +320.56 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +320.56 s |
| diarization_infer | · diarization.infer | 1 | ok | 13.48 s | 3.9 % | +320.56 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +334.05 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +334.06 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +334.07 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.16 s |
| queue | · asr.queue_wait | 1 | ok | 334.15 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.16 s |
| queue | · asr.queue_wait | 1 | ok | 334.16 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.17 s |
| queue | · asr.queue_wait | 1 | ok | 334.16 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.17 s |
| queue | · asr.queue_wait | 1 | ok | 334.17 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +334.18 s |
| queue | · asr.queue_wait | 1 | ok | 334.17 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 1.75 s | 0.5 % | +335.66 s |
| other | notes.generate | 1 | ok | 4.47 s | — | +337.41 s |
| llm_call | · llm.note_write | 1 | ok | 4.36 s | 1.3 % | +337.48 s |

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
| lid.recording | 90.00 s | 8.82 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 8.34 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 8.43 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 9.03 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 8.53 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 8.73 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 9.97 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 9.35 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 8.78 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 8.59 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 8.58 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 8.46 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 8.97 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 8.39 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 9.51 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 12.97 s | 2.018 |
| asr.chunk | faster_whisper | 7.23 s | 12.71 s | 1.759 |
| asr.chunk | faster_whisper | 6.88 s | 13.10 s | 1.905 |
| asr.chunk | faster_whisper | 6.75 s | 13.13 s | 1.945 |
| asr.chunk | faster_whisper | 7.26 s | 12.70 s | 1.750 |
| asr.chunk | faster_whisper | 7.93 s | 13.84 s | 1.744 |
| asr.chunk | faster_whisper | 8.86 s | 14.03 s | 1.584 |
| asr.chunk | faster_whisper | 5.31 s | 11.76 s | 2.216 |
| asr.chunk | faster_whisper | 5.34 s | 12.49 s | 2.339 |
| asr.chunk | faster_whisper | 5.79 s | 12.35 s | 2.134 |
| asr.chunk | faster_whisper | 17.12 s | 18.36 s | 1.073 |
| asr.chunk | faster_whisper | 8.38 s | 14.16 s | 1.690 |
| asr.chunk | faster_whisper | 4.73 s | 12.24 s | 2.587 |
| asr.chunk | faster_whisper | 2.83 s | 10.15 s | 3.581 |

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
| infer | ok | 13.48 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.75 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.36 s | 1,764 | 0 | 0 | 322 | — (not_supported) |
| **total** |  | 2 |  |  | 6.11 s | 1,776 | 0 | 0 | 328 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,976,366,592 B (2.77 GiB) → 2,974,244,864 B (2.77 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,603 B |

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

- Top critical-path stages: asr_primary 184.06 s (53.8 %); language_detection 132.48 s (38.7 %); diarization_infer 13.48 s (3.9 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: 1.8 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
