# Diagnostics — recording 27009fd6-1a94-41d2-b125-ef91d30b9668

Run `1194fd24-9109-4f57-855a-18e4e59b11c0` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 27009fd6-1a94-41d2-b125-ef91d30b9668 |
| processing_run_id | 1194fd24-9109-4f57-855a-18e4e59b11c0 |
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
| audio duration | 178.25 s |
| processing_wall_seconds | 320.31 s |
| rtf | 1.797 |
| speedup | 0.557 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.09 s | 0.0 % | -0.09 s |
| capture_input | asr.submit.probe | 1 | ok | 0.06 s | 0.0 % | -0.08 s |
| other | worker_job | 1 | ok | 310.27 s | — | +0.01 s |
| queue | · asr.queue_wait | 1 | ok | 0.01 s | 0.0 % | +0.00 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.13 s | 0.0 % | +0.01 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.15 s |
| vad | · vad.speech_runs | 1 | ok | 3.79 s | 1.2 % | +0.15 s |
| language_detection | · lid.recording | 1 | ok | 4.87 s | 1.5 % | +3.94 s |
| language_detection | · lid.run | 1 | ok | 4.67 s | 1.5 % | +8.81 s |
| language_detection | · lid.run | 1 | ok | 4.84 s | 1.5 % | +13.48 s |
| language_detection | · lid.run | 1 | ok | 4.63 s | 1.4 % | +18.33 s |
| language_detection | · lid.run | 1 | ok | 4.58 s | 1.4 % | +22.96 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 1.5 % | +27.54 s |
| language_detection | · lid.run | 1 | ok | 4.71 s | 1.5 % | +32.27 s |
| language_detection | · lid.run | 1 | ok | 4.71 s | 1.5 % | +36.98 s |
| language_detection | · lid.run | 1 | ok | 4.81 s | 1.5 % | +41.70 s |
| language_detection | · lid.run | 1 | ok | 4.73 s | 1.5 % | +46.51 s |
| language_detection | · lid.run | 1 | ok | 4.66 s | 1.5 % | +51.24 s |
| language_detection | · lid.run | 1 | ok | 4.81 s | 1.5 % | +55.90 s |
| language_detection | · lid.run | 1 | ok | 4.78 s | 1.5 % | +60.71 s |
| language_detection | · lid.run | 1 | ok | 4.85 s | 1.5 % | +65.50 s |
| language_detection | · lid.run | 1 | ok | 5.13 s | 1.6 % | +70.35 s |
| language_detection | · lid.run | 1 | ok | 5.23 s | 1.6 % | +75.48 s |
| language_detection | · lid.run | 1 | ok | 4.88 s | 1.5 % | +80.71 s |
| language_detection | · lid.run | 1 | ok | 4.95 s | 1.5 % | +85.60 s |
| language_detection | · lid.run | 1 | ok | 5.03 s | 1.6 % | +90.55 s |
| language_detection | · lid.run | 1 | ok | 5.00 s | 1.6 % | +95.58 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 1.5 % | +100.59 s |
| language_detection | · lid.run | 1 | ok | 4.93 s | 1.5 % | +105.51 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 189.22 s | 59.1 % | +110.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.11 s | 2.2 % | +110.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.52 s | 2.3 % | +117.56 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.06 s | 2.2 % | +125.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.70 s | 2.4 % | +132.15 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.27 s | 2.3 % | +139.86 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.87 s | 2.5 % | +147.13 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.79 s | 2.4 % | +155.00 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.87 s | 3.1 % | +162.80 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.37 s | 2.9 % | +172.68 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.60 s | 2.7 % | +182.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.27 s | 3.2 % | +190.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 3.1 % | +200.94 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.42 s | 2.6 % | +210.85 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.76 s | 2.4 % | +219.27 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.51 s | 3.0 % | +227.03 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.31 s | 2.9 % | +236.54 s |
| asr_primary | · · asr.chunk | 1 | ok | 9.89 s | 3.1 % | +245.87 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.28 s | 3.2 % | +255.76 s |
| asr_primary | · · asr.chunk | 1 | ok | 10.18 s | 3.2 % | +266.05 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.21 s | 2.6 % | +276.23 s |
| asr_primary | · · asr.chunk | 1 | ok | 8.16 s | 2.5 % | +284.44 s |
| asr_primary | · · asr.chunk | 1 | ok | 7.06 s | 2.2 % | +292.60 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +299.67 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +299.67 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +299.68 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +299.68 s |
| diarization_infer | · diarization.infer | 1 | ok | 10.56 s | 3.3 % | +299.68 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +310.24 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +310.25 s |
| persist | · asr.persist | 1 | ok | 0.03 s | 0.0 % | +310.25 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +310.28 s |
| queue | · asr.queue_wait | 1 | ok | 310.28 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +310.29 s |
| queue | · asr.queue_wait | 1 | ok | 310.28 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +310.29 s |
| queue | · asr.queue_wait | 1 | ok | 310.29 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +310.29 s |
| queue | · asr.queue_wait | 1 | ok | 310.29 s | — | +0.00 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +310.29 s |
| queue | · asr.queue_wait | 1 | ok | 310.29 s | — | +0.00 s |
| llm_call | llm.provider_probe | 1 | ok | 0.67 s | 0.2 % | +311.62 s |
| other | notes.generate | 1 | ok | 8.02 s | — | +312.29 s |
| llm_call | · llm.note_write | 1 | ok | 7.91 s | 2.5 % | +312.34 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 149.22 s | 22 | 1.05 s | 6.84 s | 11.64 s |

### Language checks

Language checks: 22.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 4.87 s | de | de 0.947, en 0.044, la 0.001 |
| lid.run | 7.07 s | 4.67 s | de | de 0.942, en 0.030, nn 0.009 |
| lid.run | 7.71 s | 4.84 s | de | de 0.987, en 0.008, la 0.001 |
| lid.run | 6.62 s | 4.63 s | en | en 0.988, la 0.003, nn 0.002 |
| lid.run | 7.71 s | 4.58 s | de | de 0.932, en 0.029, nn 0.008 |
| lid.run | 6.24 s | 4.73 s | de | de 0.983, en 0.008, nn 0.003 |
| lid.run | 7.07 s | 4.71 s | de | de 0.976, en 0.010, nn 0.003 |
| lid.run | 7.16 s | 4.71 s | de | de 0.983, en 0.010, nn 0.002 |
| lid.run | 6.56 s | 4.81 s | en | en 0.972, nn 0.010, la 0.007 |
| lid.run | 6.24 s | 4.73 s | de | de 0.980, nn 0.006, en 0.005 |
| lid.run | 5.88 s | 4.66 s | de | de 0.978, en 0.012, nn 0.003 |
| lid.run | 4.92 s | 4.81 s | en | en 0.960, la 0.009, nn 0.009 |
| lid.run | 6.43 s | 4.78 s | de | de 0.956, en 0.022, nn 0.005 |
| lid.run | 4.48 s | 4.85 s | de | de 0.885, en 0.031, la 0.018 |
| lid.run | 7.90 s | 5.13 s | de | de 0.997, en 0.001, nn 0.000 |
| lid.run | 10.46 s | 5.23 s | de | de 0.997, en 0.002, nn 0.000 |
| lid.run | 8.41 s | 4.88 s | de | de 0.996, en 0.002, nn 0.001 |
| lid.run | 9.66 s | 4.95 s | de | de 0.987, en 0.009, la 0.001 |
| lid.run | 11.64 s | 5.03 s | de | de 0.971, en 0.012, nn 0.004 |
| lid.run | 7.45 s | 5.00 s | de | de 0.986, en 0.008, nn 0.002 |
| lid.run | 5.88 s | 4.93 s | de | de 0.944, en 0.030, nn 0.009 |
| lid.run | 2.68 s | 4.93 s | de | de 0.958, en 0.024, nl 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 7.07 s | 7.11 s | 1.006 |
| asr.chunk | faster_whisper | 7.71 s | 7.52 s | 0.976 |
| asr.chunk | faster_whisper | 6.62 s | 7.06 s | 1.067 |
| asr.chunk | faster_whisper | 7.71 s | 7.70 s | 0.999 |
| asr.chunk | faster_whisper | 6.24 s | 7.27 s | 1.166 |
| asr.chunk | faster_whisper | 7.07 s | 7.87 s | 1.114 |
| asr.chunk | faster_whisper | 7.16 s | 7.79 s | 1.088 |
| asr.chunk | faster_whisper | 6.56 s | 9.87 s | 1.506 |
| asr.chunk | faster_whisper | 6.24 s | 9.37 s | 1.503 |
| asr.chunk | faster_whisper | 5.88 s | 8.60 s | 1.462 |
| asr.chunk | faster_whisper | 4.92 s | 10.27 s | 2.086 |
| asr.chunk | faster_whisper | 6.43 s | 9.89 s | 1.539 |
| asr.chunk | faster_whisper | 4.48 s | 8.42 s | 1.880 |
| asr.chunk | faster_whisper | 1.05 s | 7.76 s | 7.372 |
| asr.chunk | faster_whisper | 7.90 s | 9.51 s | 1.204 |
| asr.chunk | faster_whisper | 10.46 s | 9.31 s | 0.890 |
| asr.chunk | faster_whisper | 8.41 s | 9.89 s | 1.175 |
| asr.chunk | faster_whisper | 9.66 s | 10.28 s | 1.064 |
| asr.chunk | faster_whisper | 11.64 s | 10.17 s | 0.874 |
| asr.chunk | faster_whisper | 7.45 s | 8.21 s | 1.102 |
| asr.chunk | faster_whisper | 5.88 s | 8.16 s | 1.386 |
| asr.chunk | faster_whisper | 2.68 s | 7.06 s | 2.632 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 149.22 s |
| audio duration | 178.25 s |
| reprocessing ratio | 0.837 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 10.56 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 2 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.67 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 7.91 s | 2,071 | 0 | 0 | 466 | — (not_supported) |
| **total** |  | 2 |  |  | 8.58 s | 2,083 | 0 | 0 | 472 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,386,477,056 B (2.22 GiB) → 2,989,264,896 B (2.78 GiB) |
| swap used | 111,308,800 B (0.10 GiB) → 154,521,600 B (0.14 GiB) |
| memory pressure | some_avg10=0.02 → some_avg10=0.24 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,646 B |

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

- Top critical-path stages: asr_primary 189.22 s (59.1 %); language_detection 106.46 s (33.2 %); diarization_infer 10.56 s (3.3 %).
- Reprocessing ratio: 0.837.
- Cold loads: none.
- Queue wait: 0.01 s.
- LLM latency share of wall: 2.7 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
