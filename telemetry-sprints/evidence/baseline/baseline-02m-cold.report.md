# Diagnostics — recording 0b07da37-7237-4334-96a5-6ef79b1e077d

Run `ebf66ca8-aaf9-4360-8645-b5452cb3dea9` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 0b07da37-7237-4334-96a5-6ef79b1e077d |
| processing_run_id | ebf66ca8-aaf9-4360-8645-b5452cb3dea9 |
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
| processing_wall_seconds | 303.82 s |
| rtf | 2.532 |
| speedup | 0.395 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.42 s | 0.1 % | -0.45 s |
| capture_input | asr.submit.probe | 1 | ok | 0.17 s | 0.1 % | -0.36 s |
| other | worker_job | 1 | ok | 250.20 s | — | +33.64 s |
| queue | · asr.queue_wait | 1 | ok | 33.62 s | 11.1 % | +0.02 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.95 s | 0.3 % | +33.66 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +34.61 s |
| model_init | · vad.model | 1 | ok | 3.73 s | 1.2 % | +34.61 s |
| vad | · vad.speech_runs | 1 | ok | 7.24 s | 2.4 % | +38.34 s |
| language_detection | · lid.run | 1 | ok | 12.35 s | 4.1 % | +45.59 s |
| language_detection | · lid.run | 1 | ok | 10.07 s | 3.3 % | +57.95 s |
| language_detection | · lid.run | 1 | ok | 10.66 s | 3.5 % | +68.03 s |
| language_detection | · lid.run | 1 | ok | 10.74 s | 3.5 % | +78.70 s |
| language_detection | · lid.run | 1 | ok | 11.63 s | 3.8 % | +89.45 s |
| language_detection | · lid.run | 1 | ok | 11.71 s | 3.9 % | +101.09 s |
| language_detection | · lid.run | 1 | ok | 9.22 s | 3.0 % | +112.81 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 142.68 s | 47.0 % | +122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.75 s | 6.8 % | +122.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 12.96 s | 4.3 % | +142.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.69 s | 5.8 % | +155.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 35.66 s | 11.7 % | +173.46 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.71 s | 7.8 % | +209.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.19 s | 6.0 % | +232.84 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.66 s | 4.5 % | +251.03 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.03 s | 0.0 % | +264.71 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +264.74 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +264.75 s |
| diarization_load | · diarization.load | 1 | ok | 3.49 s | 1.2 % | +264.75 s |
| diarization_infer | · diarization.infer | 1 | ok | 15.46 s | 5.1 % | +268.24 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +283.71 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +283.72 s |
| persist | · asr.persist | 1 | ok | 0.11 s | 0.0 % | +283.72 s |
| llm_call | llm.provider_probe | 1 | ok | 1.53 s | 0.5 % | +297.32 s |
| other | notes.generate | 1 | ok | 4.96 s | — | +298.86 s |
| llm_call | · llm.note_write | 1 | ok | 4.72 s | 1.6 % | +299.00 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 115.72 s | 7 | 4.73 s | 18.81 s | 29.98 s |

### Language checks

Language checks: 7.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 12.35 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 10.07 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 10.66 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 10.74 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 11.63 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 11.71 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 9.22 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 20.75 s | 0.900 |
| asr.chunk | faster_whisper | 5.08 s | 12.96 s | 2.549 |
| asr.chunk | faster_whisper | 14.36 s | 17.69 s | 1.232 |
| asr.chunk | faster_whisper | 29.98 s | 35.66 s | 1.189 |
| asr.chunk | faster_whisper | 19.68 s | 23.71 s | 1.205 |
| asr.chunk | faster_whisper | 18.81 s | 18.19 s | 0.967 |
| asr.chunk | faster_whisper | 4.73 s | 13.66 s | 2.885 |

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
| load | ok | 3.49 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 15.46 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (parallel).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 1.53 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 4.72 s | 1,085 | 0 | 0 | 297 | — (not_supported) |
| **total** |  | 2 |  |  | 6.25 s | 1,097 | 0 | 0 | 303 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,444,136,448 B (2.28 GiB) → 2,381,221,888 B (2.22 GiB) |
| swap used | 639,946,752 B (0.60 GiB) → 673,918,976 B (0.63 GiB) |
| memory pressure | some_avg10=0.43 → some_avg10=0.42 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.04 s |
| telemetry buffer peak | 1,143 B |

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

- Top critical-path stages: asr_primary 142.68 s (47.0 %); language_detection 76.39 s (25.1 %); queue 33.62 s (11.1 %).
- Reprocessing ratio: 0.964.
- Cold loads: vad.model 3.73 s; diarization.load 3.49 s.
- Queue wait: 33.62 s.
- LLM latency share of wall: 2.1 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
