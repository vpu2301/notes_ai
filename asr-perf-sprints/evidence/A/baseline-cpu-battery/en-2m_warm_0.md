# Diagnostics — recording e585a1d5-81bc-49be-ad32-587a7432ce58

Run `91b65587-9412-47a5-b25f-8e515a7b1768` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | e585a1d5-81bc-49be-ad32-587a7432ce58 |
| processing_run_id | 91b65587-9412-47a5-b25f-8e515a7b1768 |
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
| processing_wall_seconds | 348.20 s |
| rtf | 3.059 |
| speedup | 0.327 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.21 s | 0.1 % | -0.21 s |
| capture_input | asr.submit.probe | 1 | ok | 0.11 s | 0.0 % | -0.16 s |
| other | worker_job | 1 | ok | 341.61 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.21 s | 0.1 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.24 s |
| vad | · vad.speech_runs | 1 | ok | 6.09 s | 1.7 % | +0.24 s |
| language_detection | · lid.recording | 1 | ok | 10.10 s | 2.9 % | +6.33 s |
| language_detection | · lid.run | 1 | ok | 9.62 s | 2.8 % | +16.44 s |
| language_detection | · lid.run | 1 | ok | 9.29 s | 2.7 % | +26.06 s |
| language_detection | · lid.run | 1 | ok | 9.17 s | 2.6 % | +35.36 s |
| language_detection | · lid.run | 1 | ok | 9.15 s | 2.6 % | +44.54 s |
| language_detection | · lid.run | 1 | ok | 9.36 s | 2.7 % | +53.69 s |
| language_detection | · lid.run | 1 | ok | 9.33 s | 2.7 % | +63.05 s |
| language_detection | · lid.run | 1 | ok | 9.20 s | 2.6 % | +72.39 s |
| language_detection | · lid.run | 1 | ok | 9.50 s | 2.7 % | +81.60 s |
| language_detection | · lid.run | 1 | ok | 8.89 s | 2.6 % | +91.10 s |
| language_detection | · lid.run | 1 | ok | 9.01 s | 2.6 % | +100.00 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 2.6 % | +109.01 s |
| language_detection | · lid.run | 1 | ok | 8.59 s | 2.5 % | +118.24 s |
| language_detection | · lid.run | 1 | ok | 8.89 s | 2.6 % | +126.83 s |
| language_detection | · lid.run | 1 | ok | 8.70 s | 2.5 % | +135.72 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 185.10 s | 53.2 % | +144.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.80 s | 4.0 % | +144.43 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.08 s | 3.8 % | +158.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.26 s | 3.5 % | +171.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.14 s | 3.8 % | +183.59 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.22 s | 3.8 % | +196.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.52 s | 3.9 % | +209.97 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.24 s | 4.1 % | +223.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.95 s | 3.7 % | +237.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.13 s | 3.5 % | +250.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.91 s | 3.7 % | +262.79 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.89 s | 5.1 % | +275.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.81 s | 4.0 % | +293.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.53 s | 3.3 % | +307.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.51 s | 3.0 % | +318.96 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +329.47 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +329.48 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +329.49 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +329.49 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.01 s | 3.4 % | +329.49 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +341.50 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +341.50 s |
| persist | · asr.persist | 1 | ok | 0.05 s | 0.0 % | +341.51 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +341.58 s |
| queue | · asr.queue_wait | 1 | ok | 341.57 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +341.58 s |
| queue | · asr.queue_wait | 1 | ok | 341.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +341.59 s |
| queue | · asr.queue_wait | 1 | ok | 341.58 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +341.59 s |
| queue | · asr.queue_wait | 1 | ok | 341.59 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.62 s | 0.2 % | +342.96 s |
| other | notes.generate | 1 | ok | 4.62 s | — | +343.58 s |
| llm_call | · llm.note_write | 1 | ok | 4.53 s | 1.3 % | +343.63 s |

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
| lid.recording | 90.00 s | 10.10 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 9.62 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 9.29 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 9.17 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 9.15 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 9.36 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 9.33 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 9.20 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 9.50 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 8.89 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 9.01 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 9.22 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 8.59 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 8.89 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 8.70 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 13.80 s | 2.147 |
| asr.chunk | faster_whisper | 7.23 s | 13.08 s | 1.810 |
| asr.chunk | faster_whisper | 6.88 s | 12.26 s | 1.783 |
| asr.chunk | faster_whisper | 6.75 s | 13.14 s | 1.948 |
| asr.chunk | faster_whisper | 7.26 s | 13.22 s | 1.821 |
| asr.chunk | faster_whisper | 7.93 s | 13.52 s | 1.704 |
| asr.chunk | faster_whisper | 8.86 s | 14.24 s | 1.607 |
| asr.chunk | faster_whisper | 5.31 s | 12.95 s | 2.440 |
| asr.chunk | faster_whisper | 5.34 s | 12.13 s | 2.271 |
| asr.chunk | faster_whisper | 5.79 s | 12.91 s | 2.231 |
| asr.chunk | faster_whisper | 17.12 s | 17.89 s | 1.045 |
| asr.chunk | faster_whisper | 8.38 s | 13.81 s | 1.648 |
| asr.chunk | faster_whisper | 4.73 s | 11.53 s | 2.437 |
| asr.chunk | faster_whisper | 2.83 s | 10.51 s | 3.708 |

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
| infer | ok | 12.01 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.62 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.53 s | 1,764 | 0 | 0 | 298 | — (not_supported) |
| **total** |  | 2 |  |  | 5.15 s | 1,776 | 0 | 0 | 304 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,020,468,224 B (2.81 GiB) → 2,976,026,624 B (2.77 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
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

- Top critical-path stages: asr_primary 185.04 s (53.1 %); language_detection 138.03 s (39.6 %); diarization_infer 12.01 s (3.4 %).
- Reprocessing ratio: 0.886.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 1.5 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
