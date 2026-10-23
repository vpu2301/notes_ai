# Diagnostics — recording dc872922-473c-4afe-a88e-ea011e764cfa

Run `763abe75-aca5-4f35-a53b-eb0d8944713f` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | dc872922-473c-4afe-a88e-ea011e764cfa |
| processing_run_id | 763abe75-aca5-4f35-a53b-eb0d8944713f |
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
| processing_wall_seconds | 187.89 s |
| rtf | 1.648 |
| speedup | 0.607 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.15 s | 0.1 % | -0.16 s |
| capture_input | asr.submit.probe | 1 | ok | 0.09 s | 0.0 % | -0.12 s |
| other | worker_job | 1 | ok | 176.81 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.12 s | 0.1 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.13 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.13 s |
| vad | · vad.speech_runs | 1 | ok | 2.15 s | 1.1 % | +0.13 s |
| language_detection | · lid.recording | 1 | ok | 5.42 s | 2.9 % | +2.28 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 2.5 % | +7.70 s |
| language_detection | · lid.run | 1 | ok | 4.88 s | 2.6 % | +12.47 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 2.5 % | +17.35 s |
| language_detection | · lid.run | 1 | ok | 4.83 s | 2.6 % | +22.00 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 2.5 % | +26.84 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 2.5 % | +31.57 s |
| language_detection | · lid.run | 1 | ok | 4.76 s | 2.5 % | +36.34 s |
| language_detection | · lid.run | 1 | ok | 4.81 s | 2.6 % | +41.10 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 2.5 % | +45.92 s |
| language_detection | · lid.run | 1 | ok | 4.79 s | 2.5 % | +50.65 s |
| language_detection | · lid.run | 1 | ok | 5.19 s | 2.8 % | +55.44 s |
| language_detection | · lid.run | 1 | ok | 4.61 s | 2.5 % | +60.65 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 104.55 s | 55.6 % | +65.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.25 s | 4.4 % | +65.26 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.70 s | 4.6 % | +73.52 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.23 s | 4.4 % | +82.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.21 s | 4.9 % | +90.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.98 s | 4.2 % | +99.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.96 s | 4.8 % | +107.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.67 s | 4.6 % | +116.63 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.23 s | 4.4 % | +125.30 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.68 s | 5.2 % | +133.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.22 s | 4.9 % | +143.22 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.92 s | 5.8 % | +152.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.45 s | 3.4 % | +163.36 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +169.81 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +169.81 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +169.82 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +169.82 s |
| diarization_infer | · diarization.infer | 1 | ok | 6.97 s | 3.7 % | +169.82 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +176.79 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +176.79 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +176.79 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +176.83 s |
| queue | · asr.queue_wait | 1 | ok | 176.83 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +176.83 s |
| queue | · asr.queue_wait | 1 | ok | 176.83 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.54 s | 0.3 % | +178.57 s |
| other | notes.generate | 1 | ok | 8.78 s | — | +179.11 s |
| llm_call | · llm.note_write | 1 | ok | 8.70 s | 4.6 % | +179.14 s |

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
| lid.recording | 90.00 s | 5.42 s | uk | uk 0.969, ru 0.030, pl 0.000 |
| lid.run | 7.45 s | 4.77 s | uk | uk 0.939, ru 0.059, it 0.000 |
| lid.run | 9.85 s | 4.88 s | uk | uk 0.930, ru 0.068, it 0.001 |
| lid.run | 7.48 s | 4.65 s | uk | uk 0.963, ru 0.034, cs 0.001 |
| lid.run | 10.49 s | 4.83 s | uk | uk 0.885, ru 0.111, it 0.001 |
| lid.run | 7.13 s | 4.73 s | uk | uk 0.861, ru 0.133, cs 0.002 |
| lid.run | 7.71 s | 4.77 s | uk | uk 0.930, ru 0.069, lt 0.000 |
| lid.run | 7.58 s | 4.76 s | uk | uk 0.983, ru 0.016, it 0.000 |
| lid.run | 6.75 s | 4.81 s | uk | uk 0.703, ru 0.294, en 0.001 |
| lid.run | 12.28 s | 4.73 s | uk | uk 0.960, ru 0.039, lt 0.000 |
| lid.run | 9.82 s | 4.79 s | uk | uk 0.950, ru 0.048, it 0.001 |
| lid.run | 14.24 s | 5.19 s | uk | uk 0.940, ru 0.060, cs 0.000 |
| lid.run | 2.64 s | 4.61 s | uk | uk 0.943, ru 0.054, pl 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.45 s | 8.25 s | 1.107 |
| asr.chunk | faster_whisper | 9.85 s | 8.70 s | 0.883 |
| asr.chunk | faster_whisper | 7.48 s | 8.23 s | 1.100 |
| asr.chunk | faster_whisper | 10.49 s | 9.21 s | 0.878 |
| asr.chunk | faster_whisper | 7.13 s | 7.98 s | 1.119 |
| asr.chunk | faster_whisper | 7.71 s | 8.96 s | 1.163 |
| asr.chunk | faster_whisper | 7.58 s | 8.67 s | 1.144 |
| asr.chunk | faster_whisper | 6.75 s | 8.23 s | 1.220 |
| asr.chunk | faster_whisper | 12.28 s | 9.68 s | 0.788 |
| asr.chunk | faster_whisper | 9.82 s | 9.22 s | 0.938 |
| asr.chunk | faster_whisper | 14.24 s | 10.92 s | 0.767 |
| asr.chunk | faster_whisper | 2.64 s | 6.45 s | 2.444 |

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
| infer | ok | 6.97 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 1.1 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.54 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 8.70 s | 2,024 | 0 | 0 | 572 | — (not_supported) |
| **total** |  | 2 |  |  | 9.23 s | 2,036 | 0 | 0 | 578 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,084,972,032 B (2.87 GiB) → 3,107,016,704 B (2.89 GiB) |
| swap used | 72,982,528 B (0.07 GiB) → 117,186,560 B (0.11 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.01 s |
| telemetry buffer peak | 1,590 B |

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

- Top critical-path stages: asr_primary 104.55 s (55.6 %); language_detection 62.94 s (33.5 %); llm_call 9.24 s (4.9 %).
- Reprocessing ratio: 0.907.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 4.9 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
