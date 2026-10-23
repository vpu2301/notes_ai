# Diagnostics — recording 30c46b48-3dc0-4e16-b23c-3c7f7ab44cd4

Run `a9cf96f7-6a68-4912-98a1-91da06b3c43d` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 30c46b48-3dc0-4e16-b23c-3c7f7ab44cd4 |
| processing_run_id | a9cf96f7-6a68-4912-98a1-91da06b3c43d |
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
| audio duration | 114.00 s |
| processing_wall_seconds | 216.00 s |
| rtf | 1.895 |
| speedup | 0.528 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.10 s | 0.0 % | -0.10 s |
| capture_input | asr.submit.probe | 1 | ok | 0.06 s | 0.0 % | -0.09 s |
| other | worker_job | 1 | ok | 193.26 s | — | +11.45 s |
| queue | · asr.queue_wait | 1 | ok | 11.45 s | 5.3 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.30 s | 0.1 % | +11.46 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +11.76 s |
| model_init | · vad.model | 1 | ok | 1.46 s | 0.7 % | +11.76 s |
| vad | · vad.speech_runs | 1 | ok | 2.40 s | 1.1 % | +13.22 s |
| language_detection | · lid.recording | 1 | ok | 5.30 s | 2.5 % | +15.62 s |
| language_detection | · lid.run | 1 | ok | 4.68 s | 2.2 % | +20.93 s |
| language_detection | · lid.run | 1 | ok | 4.70 s | 2.2 % | +25.62 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 2.2 % | +30.31 s |
| language_detection | · lid.run | 1 | ok | 4.80 s | 2.2 % | +35.10 s |
| language_detection | · lid.run | 1 | ok | 5.42 s | 2.5 % | +39.90 s |
| language_detection | · lid.run | 1 | ok | 4.84 s | 2.2 % | +45.32 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.2 % | +50.17 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 2.2 % | +55.02 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 2.3 % | +59.81 s |
| language_detection | · lid.run | 1 | ok | 5.29 s | 2.5 % | +64.74 s |
| language_detection | · lid.run | 1 | ok | 5.36 s | 2.5 % | +70.04 s |
| language_detection | · lid.run | 1 | ok | 5.06 s | 2.3 % | +75.40 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 114.01 s | 52.8 % | +80.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.25 s | 3.8 % | +80.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.26 s | 4.3 % | +88.71 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.57 s | 4.4 % | +97.98 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.05 s | 4.7 % | +107.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.71 s | 4.0 % | +117.61 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.94 s | 4.6 % | +126.33 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.02 s | 4.2 % | +136.28 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.23 s | 4.3 % | +145.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.75 s | 5.0 % | +154.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.81 s | 4.5 % | +165.29 s |
| asr_primary | · · asr.chunk | 1 | ok | 11.67 s | 5.4 % | +175.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.68 s | 3.6 % | +186.78 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +194.47 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +194.49 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +194.49 s |
| diarization_load | · diarization.load | 1 | ok | 1.80 s | 0.8 % | +194.49 s |
| diarization_infer | · diarization.infer | 1 | ok | 8.38 s | 3.9 % | +196.29 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +204.67 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +204.67 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +204.67 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +204.72 s |
| queue | · asr.queue_wait | 1 | ok | 204.72 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +204.72 s |
| queue | · asr.queue_wait | 1 | ok | 204.72 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +204.72 s |
| queue | · asr.queue_wait | 1 | ok | 204.72 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.58 s | 0.3 % | +205.87 s |
| other | notes.generate | 1 | ok | 9.54 s | — | +206.46 s |
| llm_call | · llm.note_write | 1 | ok | 9.44 s | 4.4 % | +206.51 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 103.43 s | 12 | 2.64 s | 7.64 s | 14.24 s |

### Language checks

Language checks: 13.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 5.30 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 4.68 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 4.70 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 4.78 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 4.80 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 5.42 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 4.84 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 4.85 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 4.78 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 4.93 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 5.29 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 5.36 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 5.06 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 8.25 s | 1.107 |
| asr.chunk | faster_whisper | 9.85 s | 9.26 s | 0.940 |
| asr.chunk | faster_whisper | 7.48 s | 9.57 s | 1.279 |
| asr.chunk | faster_whisper | 10.49 s | 10.05 s | 0.958 |
| asr.chunk | faster_whisper | 7.13 s | 8.71 s | 1.222 |
| asr.chunk | faster_whisper | 7.71 s | 9.94 s | 1.290 |
| asr.chunk | faster_whisper | 7.58 s | 9.02 s | 1.191 |
| asr.chunk | faster_whisper | 6.75 s | 9.23 s | 1.368 |
| asr.chunk | faster_whisper | 12.28 s | 10.75 s | 0.875 |
| asr.chunk | faster_whisper | 9.82 s | 9.81 s | 0.999 |
| asr.chunk | faster_whisper | 14.24 s | 11.67 s | 0.820 |
| asr.chunk | faster_whisper | 2.64 s | 7.68 s | 2.910 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 103.43 s |
| audio duration | 114.00 s |
| reprocessing ratio | 0.907 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 1.80 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 8.38 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.58 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 9.44 s | 2,024 | 0 | 0 | 578 | — (not_supported) |
| **total** |  | 2 |  |  | 10.02 s | 2,036 | 0 | 0 | 584 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,712,896 B (2.29 GiB) → 3,096,240,128 B (2.88 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.08 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,171 B |

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

- Top critical-path stages: asr_primary 114.01 s (52.8 %); language_detection 64.80 s (30.0 %); queue 11.45 s (5.3 %).
- Reprocessing ratio: 0.907.
- Cold loads: vad.model 1.46 s; diarization.load 1.80 s.
- Queue wait: 11.45 s.
- LLM latency share of wall: 4.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
