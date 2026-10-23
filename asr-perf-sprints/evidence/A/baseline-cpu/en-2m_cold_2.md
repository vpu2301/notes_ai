# Diagnostics — recording 8c6ca546-d9dd-4937-a9fa-f354faae7949

Run `933c6010-dcc8-4b61-8038-00f6fb063d4e` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 8c6ca546-d9dd-4937-a9fa-f354faae7949 |
| processing_run_id | 933c6010-dcc8-4b61-8038-00f6fb063d4e |
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
| processing_wall_seconds | 199.86 s |
| rtf | 1.756 |
| speedup | 0.570 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.14 s | 0.1 % | -0.15 s |
| capture_input | asr.submit.probe | 1 | ok | 0.07 s | 0.0 % | -0.12 s |
| other | worker_job | 1 | ok | 182.18 s | — | +11.37 s |
| queue | · asr.queue_wait | 1 | ok | 11.36 s | 5.7 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.33 s | 0.2 % | +11.37 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +11.70 s |
| model_init | · vad.model | 1 | ok | 1.31 s | 0.7 % | +11.70 s |
| vad | · vad.speech_runs | 1 | ok | 3.87 s | 1.9 % | +13.01 s |
| language_detection | · lid.recording | 1 | ok | 4.89 s | 2.4 % | +16.88 s |
| language_detection | · lid.run | 1 | ok | 4.40 s | 2.2 % | +21.77 s |
| language_detection | · lid.run | 1 | ok | 4.65 s | 2.3 % | +26.17 s |
| language_detection | · lid.run | 1 | ok | 4.96 s | 2.5 % | +30.83 s |
| language_detection | · lid.run | 1 | ok | 4.57 s | 2.3 % | +35.79 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 2.4 % | +40.37 s |
| language_detection | · lid.run | 1 | ok | 4.77 s | 2.4 % | +45.26 s |
| language_detection | · lid.run | 1 | ok | 4.70 s | 2.4 % | +50.03 s |
| language_detection | · lid.run | 1 | ok | 4.49 s | 2.2 % | +54.73 s |
| language_detection | · lid.run | 1 | ok | 4.45 s | 2.2 % | +59.23 s |
| language_detection | · lid.run | 1 | ok | 4.49 s | 2.2 % | +63.68 s |
| language_detection | · lid.run | 1 | ok | 4.49 s | 2.2 % | +68.17 s |
| language_detection | · lid.run | 1 | ok | 4.52 s | 2.3 % | +72.66 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 2.5 % | +77.18 s |
| language_detection | · lid.run | 1 | ok | 4.89 s | 2.4 % | +82.11 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 97.93 s | 49.0 % | +87.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.57 s | 3.3 % | +87.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.58 s | 3.3 % | +93.57 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.90 s | 3.5 % | +100.16 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.01 s | 3.5 % | +107.07 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.97 s | 3.5 % | +114.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.05 s | 3.5 % | +121.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.43 s | 3.7 % | +128.11 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.39 s | 3.2 % | +135.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.46 s | 3.2 % | +141.92 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.93 s | 3.5 % | +148.38 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.64 s | 4.8 % | +155.32 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.37 s | 3.7 % | +164.96 s |
| asr_primary | · · asr.chunk | 1 | ok | 6.68 s | 3.3 % | +172.34 s |
| asr_primary | · · asr.chunk | 1 | ok | 5.91 s | 3.0 % | +179.02 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.01 s | 0.0 % | +184.93 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +184.95 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +184.95 s |
| diarization_load | · diarization.load | 1 | ok | 1.70 s | 0.8 % | +184.95 s |
| diarization_infer | · diarization.infer | 1 | ok | 6.86 s | 3.4 % | +186.65 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +193.51 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +193.51 s |
| persist | · asr.persist | 1 | ok | 0.02 s | 0.0 % | +193.51 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +193.55 s |
| queue | · asr.queue_wait | 1 | ok | 193.55 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +193.55 s |
| queue | · asr.queue_wait | 1 | ok | 193.55 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +193.55 s |
| queue | · asr.queue_wait | 1 | ok | 193.55 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.67 s | 0.3 % | +195.14 s |
| other | notes.generate | 1 | ok | 4.05 s | — | +195.81 s |
| llm_call | · llm.note_write | 1 | ok | 3.95 s | 2.0 % | +195.87 s |

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
| lid.recording | 90.00 s | 4.89 s | en | en 0.998, de 0.001, es 0.000 |
| lid.run | 6.43 s | 4.40 s | en | en 0.998, ja 0.000, cy 0.000 |
| lid.run | 7.23 s | 4.65 s | en | en 0.987, de 0.002, ja 0.001 |
| lid.run | 6.88 s | 4.96 s | en | en 0.995, ja 0.001, de 0.001 |
| lid.run | 6.75 s | 4.57 s | en | en 0.990, ja 0.002, cy 0.001 |
| lid.run | 7.26 s | 4.89 s | en | en 0.996, ja 0.001, es 0.000 |
| lid.run | 7.93 s | 4.77 s | en | en 0.990, ja 0.002, ko 0.001 |
| lid.run | 8.86 s | 4.70 s | en | en 0.998, ja 0.001, es 0.000 |
| lid.run | 5.31 s | 4.49 s | en | en 0.989, cy 0.001, ja 0.001 |
| lid.run | 5.34 s | 4.45 s | en | en 0.996, ja 0.001, cy 0.001 |
| lid.run | 5.79 s | 4.49 s | en | en 0.990, ja 0.002, nn 0.001 |
| lid.run | 17.12 s | 4.49 s | en | en 0.996, ja 0.001, es 0.001 |
| lid.run | 8.38 s | 4.52 s | en | en 0.995, ja 0.001, es 0.001 |
| lid.run | 4.73 s | 4.93 s | en | en 0.985, nn 0.003, ja 0.002 |
| lid.run | 2.83 s | 4.89 s | en | en 0.992, ja 0.002, es 0.001 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 6.43 s | 6.57 s | 1.022 |
| asr.chunk | faster_whisper | 7.23 s | 6.58 s | 0.911 |
| asr.chunk | faster_whisper | 6.88 s | 6.90 s | 1.004 |
| asr.chunk | faster_whisper | 6.75 s | 7.01 s | 1.038 |
| asr.chunk | faster_whisper | 7.26 s | 6.97 s | 0.960 |
| asr.chunk | faster_whisper | 7.93 s | 7.05 s | 0.889 |
| asr.chunk | faster_whisper | 8.86 s | 7.42 s | 0.838 |
| asr.chunk | faster_whisper | 5.31 s | 6.39 s | 1.203 |
| asr.chunk | faster_whisper | 5.34 s | 6.46 s | 1.209 |
| asr.chunk | faster_whisper | 5.79 s | 6.93 s | 1.197 |
| asr.chunk | faster_whisper | 17.12 s | 9.64 s | 0.563 |
| asr.chunk | faster_whisper | 8.38 s | 7.37 s | 0.880 |
| asr.chunk | faster_whisper | 4.73 s | 6.68 s | 1.411 |
| asr.chunk | faster_whisper | 2.83 s | 5.91 s | 2.086 |

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
| load | ok | 1.70 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 6.86 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: -0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.67 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 3.95 s | 1,764 | 0 | 0 | 272 | — (not_supported) |
| **total** |  | 2 |  |  | 4.62 s | 1,776 | 0 | 0 | 278 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,456,018,944 B (2.29 GiB) → 2,959,937,536 B (2.76 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.39 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,173 B |

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

- Top critical-path stages: asr_primary 97.93 s (49.0 %); language_detection 70.07 s (35.1 %); queue 11.36 s (5.7 %).
- Reprocessing ratio: 0.886.
- Cold loads: vad.model 1.31 s; diarization.load 1.70 s.
- Queue wait: 11.36 s.
- LLM latency share of wall: 2.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
