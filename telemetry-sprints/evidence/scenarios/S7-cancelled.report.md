# Diagnostics — recording ec4f4e12-2d81-4207-b67b-34899cf28920

Run `351eccc5-b48c-4a6c-998c-0b996fce9c14` · initial · cancelled

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | ec4f4e12-2d81-4207-b67b-34899cf28920 |
| processing_run_id | 351eccc5-b48c-4a6c-998c-0b996fce9c14 |
| kind | initial |
| trigger | user |
| status | cancelled |
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
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 900.00 s |
| processing_wall_seconds | 91.62 s |
| rtf | 0.102 |
| speedup | 9.823 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.56 s | 0.6 % | -0.57 s |
| capture_input | asr.submit.probe | 1 | ok | 0.15 s | 0.2 % | -0.39 s |
| other | worker_job | 1 | cancelled | 91.60 s | — | +0.02 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.79 s | 0.9 % | +0.03 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +0.83 s |
| model_init | · vad.model | 1 | ok | 0.00 s | 0.0 % | +0.83 s |
| vad | · vad.speech_runs | 1 | ok | 36.51 s | 39.8 % | +0.83 s |
| language_detection | · lid.run | 1 | ok | 11.98 s | 13.1 % | +37.37 s |
| language_detection | · lid.run | 1 | ok | 11.38 s | 12.4 % | +49.36 s |
| language_detection | · lid.run | 1 | ok | 10.13 s | 11.1 % | +60.75 s |
| language_detection | · lid.run | 1 | ok | 10.65 s | 11.6 % | +70.89 s |
| language_detection | · lid.run | 1 | ok | 10.03 s | 11.0 % | +81.55 s |
| other | worker_job | 1 | cancelled | 0.00 s | — | +91.64 s |
| queue | · asr.queue_wait | 1 | ok | 91.64 s | — | +0.01 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 866.14 s | 61 | 1.12 s | 11.42 s | 30.00 s |

### Language checks

Language checks: 5.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.run | 10.68 s | 11.98 s | en | en 0.982, cy 0.008, la 0.003 |
| lid.run | 14.91 s | 11.38 s | en | en 0.995, cy 0.003, la 0.000 |
| lid.run | 8.44 s | 10.13 s | en | en 0.996, cy 0.002, la 0.001 |
| lid.run | 2.04 s | 10.65 s | en | en 0.975, cy 0.007, nn 0.002 |
| lid.run | 4.89 s | 10.03 s | en | en 0.986, cy 0.009, la 0.001 |

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 900.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,389,872,640 B (2.23 GiB) → 3,113,046,016 B (2.90 GiB) |
| swap used | 1,238,114,304 B (1.15 GiB) → 1,237,303,296 B (1.15 GiB) |
| memory pressure | some_avg10=0.18 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.10 s |
| telemetry buffer peak | 1,114 B |

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
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: language_detection 54.19 s (59.1 %); vad 36.51 s (39.8 %); audio_prep 0.79 s (0.9 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `cold_model_init`, `swap_growth`.
