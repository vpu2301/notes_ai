# Diagnostics — recording f62d34b2-2f96-4233-bb74-e8052660469c

Run `d9ebb2f2-21b2-4405-9dec-7ae652534d81` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | f62d34b2-2f96-4233-bb74-e8052660469c |
| processing_run_id | d9ebb2f2-21b2-4405-9dec-7ae652534d81 |
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
| processing_wall_seconds | 372.41 s |
| rtf | 3.271 |
| speedup | 0.306 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.31 s | 0.1 % | -0.32 s |
| capture_input | asr.submit.probe | 1 | ok | 0.18 s | 0.0 % | -0.30 s |
| other | worker_job | 1 | ok | 336.06 s | — | +26.78 s |
| queue | · asr.queue_wait | 1 | ok | 26.77 s | 7.2 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.77 s | 0.2 % | +26.80 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +27.57 s |
| model_init | · vad.model | 1 | ok | 2.79 s | 0.7 % | +27.57 s |
| vad | · vad.speech_runs | 1 | ok | 3.18 s | 0.9 % | +30.36 s |
| language_detection | · lid.recording | 1 | ok | 9.03 s | 2.4 % | +33.55 s |
| language_detection | · lid.run | 1 | ok | 10.28 s | 2.8 % | +42.57 s |
| language_detection | · lid.run | 1 | ok | 10.37 s | 2.8 % | +52.86 s |
| language_detection | · lid.run | 1 | ok | 9.65 s | 2.6 % | +63.25 s |
| language_detection | · lid.run | 1 | ok | 8.98 s | 2.4 % | +72.90 s |
| language_detection | · lid.run | 1 | ok | 9.34 s | 2.5 % | +81.89 s |
| language_detection | · lid.run | 1 | ok | 9.39 s | 2.5 % | +91.23 s |
| language_detection | · lid.run | 1 | ok | 9.21 s | 2.5 % | +100.64 s |
| language_detection | · lid.run | 1 | ok | 9.09 s | 2.4 % | +109.85 s |
| language_detection | · lid.run | 1 | ok | 9.42 s | 2.5 % | +118.94 s |
| language_detection | · lid.run | 1 | ok | 9.12 s | 2.4 % | +128.37 s |
| language_detection | · lid.run | 1 | ok | 9.05 s | 2.4 % | +137.51 s |
| language_detection | · lid.run | 1 | ok | 9.20 s | 2.5 % | +146.56 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 189.08 s | 50.8 % | +155.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.95 s | 4.0 % | +155.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.08 s | 3.8 % | +170.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.78 s | 3.7 % | +184.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.40 s | 3.9 % | +198.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.94 s | 3.7 % | +213.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.65 s | 3.9 % | +226.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.41 s | 3.6 % | +241.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.70 s | 3.9 % | +255.01 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.76 s | 4.0 % | +269.72 s |
| asr_primary | · · asr.chunk | 1 | ok | 15.11 s | 4.1 % | +284.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 16.20 s | 4.3 % | +299.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.83 s | 4.0 % | +315.81 s |
| asr_primary | · · asr.chunk | 1 | ok | 14.16 s | 3.8 % | +330.65 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.04 s | 0.0 % | +344.84 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +344.89 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +344.89 s |
| diarization_load | · diarization.load | 1 | ok | 4.95 s | 1.3 % | +344.89 s |
| diarization_infer | · diarization.infer | 1 | ok | 12.86 s | 3.5 % | +349.85 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +362.71 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +362.72 s |
| persist | · asr.persist | 1 | ok | 0.10 s | 0.0 % | +362.72 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +362.87 s |
| queue | · asr.queue_wait | 1 | ok | 362.86 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +362.87 s |
| queue | · asr.queue_wait | 1 | ok | 362.86 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +362.88 s |
| queue | · asr.queue_wait | 1 | ok | 362.87 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +362.88 s |
| queue | · asr.queue_wait | 1 | ok | 362.87 s | — | +0.01 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +362.89 s |
| queue | · asr.queue_wait | 1 | ok | 362.88 s | — | +0.01 s |
| llm_call | llm.provider_probe | 1 | ok | 0.98 s | 0.3 % | +364.49 s |
| other | notes.generate | 1 | ok | 6.94 s | — | +365.48 s |
| llm_call | · llm.note_write | 1 | ok | 6.77 s | 1.8 % | +365.58 s |

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
| lid.recording | 90.00 s | 9.03 s | de | de 0.998, en 0.001, es 0.000 |
| lid.run | 8.83 s | 10.28 s | de | de 0.990, en 0.005, ja 0.001 |
| lid.run | 8.92 s | 10.37 s | de | de 0.992, en 0.004, la 0.001 |
| lid.run | 5.85 s | 9.65 s | de | de 0.993, en 0.004, ja 0.001 |
| lid.run | 9.95 s | 8.98 s | de | de 0.993, en 0.003, nn 0.002 |
| lid.run | 8.16 s | 9.34 s | de | de 0.995, en 0.003, ja 0.000 |
| lid.run | 9.63 s | 9.39 s | de | de 0.995, en 0.004, ru 0.000 |
| lid.run | 5.85 s | 9.21 s | de | de 0.999, en 0.001, ja 0.000 |
| lid.run | 9.88 s | 9.09 s | de | de 0.994, en 0.003, nn 0.000 |
| lid.run | 7.04 s | 9.42 s | de | de 0.999, en 0.000, ja 0.000 |
| lid.run | 9.63 s | 9.12 s | de | de 0.990, en 0.006, nn 0.001 |
| lid.run | 8.35 s | 9.05 s | de | de 0.993, en 0.003, ja 0.001 |
| lid.run | 3.64 s | 9.20 s | de | de 0.960, en 0.023, la 0.003 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 8.83 s | 14.95 s | 1.693 |
| asr.chunk | faster_whisper | 8.92 s | 14.08 s | 1.578 |
| asr.chunk | faster_whisper | 5.85 s | 13.78 s | 2.354 |
| asr.chunk | faster_whisper | 9.95 s | 14.40 s | 1.447 |
| asr.chunk | faster_whisper | 8.16 s | 13.94 s | 1.709 |
| asr.chunk | faster_whisper | 9.63 s | 14.65 s | 1.522 |
| asr.chunk | faster_whisper | 5.85 s | 13.41 s | 2.291 |
| asr.chunk | faster_whisper | 9.88 s | 14.70 s | 1.488 |
| asr.chunk | faster_whisper | 7.04 s | 14.76 s | 2.098 |
| asr.chunk | faster_whisper | 9.63 s | 15.11 s | 1.569 |
| asr.chunk | faster_whisper | 8.35 s | 16.20 s | 1.940 |
| asr.chunk | faster_whisper | 3.64 s | 14.83 s | 4.069 |
| asr.chunk | faster_whisper | 1.93 s | 14.16 s | 7.334 |

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
| load | ok | 4.95 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 12.86 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.5 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.98 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.76 s | 1,820 | 0 | 0 | 295 | — (not_supported) |
| **total** |  | 2 |  |  | 7.74 s | 1,832 | 0 | 0 | 301 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,571,904 B (2.29 GiB) → 2,974,937,088 B (2.77 GiB) |
| swap used | 1,278,902,272 B (1.19 GiB) → 1,277,112,320 B (1.19 GiB) |
| memory pressure | some_avg10=0.22 → some_avg10=0.98 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.05 s |
| telemetry buffer peak | 1,175 B |

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

- Top critical-path stages: asr_primary 189.08 s (50.8 %); language_detection 122.13 s (32.8 %); queue 26.77 s (7.2 %).
- Reprocessing ratio: 0.858.
- Cold loads: vad.model 2.79 s; diarization.load 4.95 s.
- Queue wait: 26.77 s.
- LLM latency share of wall: 2.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
