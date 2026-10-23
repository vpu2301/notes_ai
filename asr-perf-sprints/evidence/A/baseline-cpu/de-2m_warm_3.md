# Diagnostics — recording 0ea49dd9-1468-4b7d-95a4-3b16cc01e8a4

Run `d894cdf5-c7ce-42ee-be62-ea882024cea8` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 0ea49dd9-1468-4b7d-95a4-3b16cc01e8a4 |
| processing_run_id | d894cdf5-c7ce-42ee-be62-ea882024cea8 |
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
| audio duration | 113.87 s |
| processing_wall_seconds | 223.78 s |
| rtf | 1.965 |
| speedup | 0.509 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.09 s | 0.0 % | -0.10 s |
| capture_input | asr.submit.probe | 1 | ok | 0.06 s | 0.0 % | -0.09 s |
| other | worker_job | 1 | ok | 217.24 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.13 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| vad | · vad.speech_runs | 1 | ok | 4.23 s | 1.9 % | +0.15 s |
| language_detection | · lid.recording | 1 | ok | 7.20 s | 3.2 % | +4.38 s |
| language_detection | · lid.run | 1 | ok | 6.42 s | 2.9 % | +11.59 s |
| language_detection | · lid.run | 1 | ok | 6.20 s | 2.8 % | +18.01 s |
| language_detection | · lid.run | 1 | ok | 6.33 s | 2.8 % | +24.21 s |
| language_detection | · lid.run | 1 | ok | 6.13 s | 2.7 % | +30.54 s |
| language_detection | · lid.run | 1 | ok | 7.04 s | 3.1 % | +36.67 s |
| language_detection | · lid.run | 1 | ok | 6.87 s | 3.1 % | +43.71 s |
| language_detection | · lid.run | 1 | ok | 5.87 s | 2.6 % | +50.59 s |
| language_detection | · lid.run | 1 | ok | 6.83 s | 3.1 % | +56.47 s |
| language_detection | · lid.run | 1 | ok | 6.06 s | 2.7 % | +63.30 s |
| language_detection | · lid.run | 1 | ok | 6.52 s | 2.9 % | +69.36 s |
| language_detection | · lid.run | 1 | ok | 6.35 s | 2.8 % | +75.89 s |
| language_detection | · lid.run | 1 | ok | 5.91 s | 2.6 % | +82.24 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 120.81 s | 54.0 % | +88.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.84 s | 3.9 % | +88.14 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.45 s | 4.2 % | +96.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.13 s | 4.1 % | +106.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.04 s | 4.5 % | +115.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.25 s | 5.0 % | +125.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.02 s | 4.5 % | +136.88 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.89 s | 4.0 % | +146.91 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.16 s | 4.1 % | +155.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 4.3 % | +164.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.97 s | 4.5 % | +174.65 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 4.0 % | +184.62 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.99 s | 3.6 % | +193.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.38 s | 3.3 % | +201.58 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +208.96 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +208.96 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +208.97 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +208.97 s |
| diarization_infer | · diarization.infer | 1 | ok | 8.23 s | 3.7 % | +208.97 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +217.20 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +217.21 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +217.21 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +217.26 s |
| queue | · asr.queue_wait | 1 | ok | 217.26 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +217.26 s |
| queue | · asr.queue_wait | 1 | ok | 217.26 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.69 s | 0.3 % | +218.38 s |
| other | notes.generate | 1 | ok | 4.71 s | — | +219.07 s |
| llm_call | · llm.note_write | 1 | ok | 4.60 s | 2.1 % | +219.13 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 97.66 s | 13 | 1.93 s | 8.35 s | 9.95 s |

### Language checks

Language checks: 13.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 7.20 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 6.42 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 6.20 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 6.33 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 6.13 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 7.04 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 6.87 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 5.87 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 6.83 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 6.06 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 6.52 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 6.35 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 5.91 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 8.84 s | 1.001 |
| asr.chunk | faster_whisper | 8.92 s | 9.45 s | 1.059 |
| asr.chunk | faster_whisper | 5.85 s | 9.13 s | 1.559 |
| asr.chunk | faster_whisper | 9.95 s | 10.04 s | 1.009 |
| asr.chunk | faster_whisper | 8.16 s | 11.25 s | 1.379 |
| asr.chunk | faster_whisper | 9.63 s | 10.02 s | 1.041 |
| asr.chunk | faster_whisper | 5.85 s | 8.89 s | 1.519 |
| asr.chunk | faster_whisper | 9.88 s | 9.16 s | 0.927 |
| asr.chunk | faster_whisper | 7.04 s | 9.68 s | 1.376 |
| asr.chunk | faster_whisper | 9.63 s | 9.97 s | 1.035 |
| asr.chunk | faster_whisper | 8.35 s | 8.96 s | 1.073 |
| asr.chunk | faster_whisper | 3.64 s | 7.99 s | 2.193 |
| asr.chunk | faster_whisper | 1.93 s | 7.38 s | 3.820 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 97.66 s |
| audio duration | 113.87 s |
| reprocessing ratio | 0.858 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 8.23 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.69 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.60 s | 1,820 | 0 | 0 | 326 | — (not_supported) |
| **total** |  | 2 |  |  | 5.29 s | 1,832 | 0 | 0 | 332 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,401,857,536 B (2.24 GiB) → 3,114,897,408 B (2.90 GiB) |
| swap used | 21,438,464 B (0.02 GiB) → 31,252,480 B (0.03 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,593 B |

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

- Top critical-path stages: asr_primary 120.81 s (54.0 %); language_detection 83.72 s (37.4 %); diarization_infer 8.23 s (3.7 %).
- Reprocessing ratio: 0.858.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.4 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
