# Diagnostics — recording bc460637-23b9-4d4b-9968-dfd494cb5ac9

Run `e3290649-c4f0-4614-94b6-43223f04c2fd` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | bc460637-23b9-4d4b-9968-dfd494cb5ac9 |
| processing_run_id | e3290649-c4f0-4614-94b6-43223f04c2fd |
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
| processing_wall_seconds | 537.85 s |
| rtf | 4.482 |
| speedup | 0.223 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.67 s | 0.1 % | -0.69 s |
| capture_input | asr.submit.probe | 1 | ok | 0.32 s | 0.1 % | -0.50 s |
| other | worker_job | 1 | ok | 241.48 s | — | +280.52 s |
| queue | · asr.queue_wait | 1 | ok | 280.50 s | 52.2 % | +0.02 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.28 s | 0.1 % | +280.52 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +280.80 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +280.80 s |
| vad | · vad.speech_runs | 1 | ok | 3.34 s | 0.6 % | +280.80 s |
| language_detection | · lid.run | 1 | ok | 9.62 s | 1.8 % | +284.14 s |
| language_detection | · lid.run | 1 | ok | 9.44 s | 1.8 % | +293.77 s |
| language_detection | · lid.run | 1 | ok | 9.77 s | 1.8 % | +303.22 s |
| language_detection | · lid.run | 1 | ok | 9.71 s | 1.8 % | +312.99 s |
| language_detection | · lid.run | 1 | ok | 9.52 s | 1.8 % | +322.70 s |
| language_detection | · lid.run | 1 | ok | 9.57 s | 1.8 % | +332.22 s |
| language_detection | · lid.run | 1 | ok | 9.69 s | 1.8 % | +341.80 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 153.49 s | 28.5 % | +351.48 s |
| asr_primary | · · asr.chunk | 1 | ok | 20.25 s | 3.8 % | +351.49 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.61 s | 2.5 % | +371.74 s |
| asr_primary | · · asr.chunk | 1 | ok | 17.74 s | 3.3 % | +385.35 s |
| asr_primary | · · asr.chunk | 1 | ok | 36.99 s | 6.9 % | +403.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.58 s | 5.1 % | +440.09 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.33 s | 4.3 % | +467.66 s |
| asr_primary | · · asr.chunk | 1 | ok | 13.95 s | 2.6 % | +491.03 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +504.98 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +504.98 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +504.99 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +504.99 s |
| diarization_infer | · diarization.infer | 1 | ok | 16.91 s | 3.1 % | +504.99 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.01 s | 0.0 % | +521.90 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +521.91 s |
| persist | · asr.persist | 1 | ok | 0.07 s | 0.0 % | +521.92 s |
| other | worker_job | 1 | skipped | 0.01 s | — | +522.03 s |
| queue | · asr.queue_wait | 1 | ok | 522.01 s | — | +0.02 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +522.03 s |
| queue | · asr.queue_wait | 1 | ok | 522.02 s | — | +0.02 s |
| llm_call | llm.provider_probe | 1 | ok | 2.02 s | 0.4 % | +529.32 s |
| other | notes.generate | 1 | ok | 6.51 s | — | +531.34 s |
| llm_call | · llm.note_write | 1 | ok | 6.39 s | 1.2 % | +531.41 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 115.72 s | 7 | 4.73 s | 18.81 s | 29.98 s |

### Language checks

Language checks: 7.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 23.07 s | 9.62 s | en | en 0.993, cy 0.002, pt 0.001 |
| lid.run | 5.08 s | 9.44 s | en | en 0.986, cy 0.004, la 0.001 |
| lid.run | 14.36 s | 9.77 s | en | en 0.980, cy 0.008, es 0.001 |
| lid.run | 29.98 s | 9.71 s | en | en 0.994, cy 0.004, fr 0.000 |
| lid.run | 19.68 s | 9.52 s | en | en 0.994, cy 0.002, nn 0.001 |
| lid.run | 18.81 s | 9.57 s | en | en 0.966, cy 0.019, nn 0.004 |
| lid.run | 4.73 s | 9.69 s | en | en 0.933, nn 0.020, la 0.012 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 23.07 s | 20.25 s | 0.878 |
| asr.chunk | faster_whisper | 5.08 s | 13.61 s | 2.677 |
| asr.chunk | faster_whisper | 14.36 s | 17.74 s | 1.235 |
| asr.chunk | faster_whisper | 29.98 s | 36.99 s | 1.234 |
| asr.chunk | faster_whisper | 19.68 s | 27.58 s | 1.402 |
| asr.chunk | faster_whisper | 18.81 s | 23.33 s | 1.240 |
| asr.chunk | faster_whisper | 4.73 s | 13.95 s | 2.946 |

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
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 16.91 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 3 | 9.2 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 2.02 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 6.39 s | 1,085 | 0 | 0 | 290 | — (not_supported) |
| **total** |  | 2 |  |  | 8.41 s | 1,097 | 0 | 0 | 296 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 3,134,242,816 B (2.92 GiB) → 3,059,970,048 B (2.85 GiB) |
| swap used | 681,644,032 B (0.63 GiB) → 681,644,032 B (0.63 GiB) |
| memory pressure | some_avg10=0.06 → some_avg10=0.42 |
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.02 s |
| telemetry buffer peak | 1,558 B |

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

- Top critical-path stages: queue 280.50 s (52.2 %); asr_primary 153.50 s (28.5 %); language_detection 67.31 s (12.5 %).
- Reprocessing ratio: 0.964.
- Cold loads: none.
- Queue wait: 280.50 s.
- LLM latency share of wall: 1.6 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
