# Diagnostics — recording b77ef3ca-544d-45b5-93f6-3e6a5be4b9be

Run `8bc3c534-d8e9-448a-9a19-0e2eb1467830` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | b77ef3ca-544d-45b5-93f6-3e6a5be4b9be |
| processing_run_id | 8bc3c534-d8e9-448a-9a19-0e2eb1467830 |
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
| processing_wall_seconds | 189.16 s |
| rtf | 1.659 |
| speedup | 0.603 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.12 s | 0.1 % | -0.13 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.11 s |
| other | worker_job | 1 | ok | 179.44 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.12 s | 0.1 % | +0.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.14 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.14 s |
| vad | · vad.speech_runs | 1 | ok | 2.03 s | 1.1 % | +0.14 s |
| language_detection | · lid.recording | 1 | ok | 5.69 s | 3.0 % | +2.17 s |
| language_detection | · lid.run | 1 | ok | 5.25 s | 2.8 % | +7.87 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 2.6 % | +13.12 s |
| language_detection | · lid.run | 1 | ok | 4.90 s | 2.6 % | +17.94 s |
| language_detection | · lid.run | 1 | ok | 4.84 s | 2.6 % | +22.84 s |
| language_detection | · lid.run | 1 | ok | 4.98 s | 2.6 % | +27.68 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 2.6 % | +32.66 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 2.6 % | +37.49 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 2.7 % | +42.34 s |
| language_detection | · lid.run | 1 | ok | 4.97 s | 2.6 % | +47.36 s |
| language_detection | · lid.run | 1 | ok | 4.79 s | 2.5 % | +52.34 s |
| language_detection | · lid.run | 1 | ok | 5.02 s | 2.7 % | +57.12 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 2.6 % | +62.14 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 105.64 s | 55.8 % | +67.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.49 s | 4.5 % | +67.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.10 s | 4.8 % | +75.53 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.35 s | 4.4 % | +84.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.94 s | 4.7 % | +92.99 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.65 s | 4.6 % | +101.93 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.92 s | 4.7 % | +110.58 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.54 s | 4.5 % | +119.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.45 s | 4.5 % | +128.04 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.92 s | 5.2 % | +136.50 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.82 s | 4.7 % | +146.42 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.80 s | 5.7 % | +155.24 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.63 s | 3.5 % | +166.04 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +172.68 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +172.68 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +172.68 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +172.68 s |
| diarization_infer | · diarization.infer | 1 | ok | 6.72 s | 3.6 % | +172.68 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +179.40 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +179.41 s |
| persist | · asr.persist | 1 | ok | 0.04 s | 0.0 % | +179.41 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +179.46 s |
| queue | · asr.queue_wait | 1 | ok | 179.46 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +179.47 s |
| queue | · asr.queue_wait | 1 | ok | 179.46 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.77 s | 0.4 % | +180.50 s |
| other | notes.generate | 1 | ok | 7.89 s | — | +181.27 s |
| llm_call | · llm.note_write | 1 | ok | 7.79 s | 4.1 % | +181.31 s |

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
| lid.recording | 90.00 s | 5.69 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 5.25 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 4.83 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 4.90 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 4.84 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 4.98 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 4.83 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 4.85 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 5.02 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 4.97 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 4.79 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 5.02 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 4.89 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 8.49 s | 1.139 |
| asr.chunk | faster_whisper | 9.85 s | 9.10 s | 0.923 |
| asr.chunk | faster_whisper | 7.48 s | 8.35 s | 1.116 |
| asr.chunk | faster_whisper | 10.49 s | 8.94 s | 0.852 |
| asr.chunk | faster_whisper | 7.13 s | 8.65 s | 1.212 |
| asr.chunk | faster_whisper | 7.71 s | 8.92 s | 1.157 |
| asr.chunk | faster_whisper | 7.58 s | 8.54 s | 1.126 |
| asr.chunk | faster_whisper | 6.75 s | 8.45 s | 1.253 |
| asr.chunk | faster_whisper | 12.28 s | 9.92 s | 0.808 |
| asr.chunk | faster_whisper | 9.82 s | 8.82 s | 0.898 |
| asr.chunk | faster_whisper | 14.24 s | 10.80 s | 0.759 |
| asr.chunk | faster_whisper | 2.64 s | 6.63 s | 2.513 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 6.72 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.77 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.79 s | 2,024 | 0 | 0 | 502 | — (not_supported) |
| **total** |  | 2 |  |  | 8.56 s | 2,036 | 0 | 0 | 508 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,387,398,656 B (2.22 GiB) → 3,100,594,176 B (2.89 GiB) |
| swap used | 111,071,232 B (0.10 GiB) → 110,972,928 B (0.10 GiB) |
| memory pressure | some_avg10=0.02 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,586 B |

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

- Top critical-path stages: asr_primary 105.64 s (55.8 %); language_detection 64.84 s (34.3 %); llm_call 8.56 s (4.5 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 4.5 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
