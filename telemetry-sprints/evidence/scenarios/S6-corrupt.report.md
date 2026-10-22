# Diagnostics — recording eb2040bd-280c-409d-b10d-61f8c9a083b6

Run `52f7bff1-1575-4eef-84e7-fd230ec53f01` · initial · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | eb2040bd-280c-409d-b10d-61f8c9a083b6 |
| processing_run_id | 52f7bff1-1575-4eef-84e7-fd230ec53f01 |
| kind | initial |
| trigger | user |
| status | failed |
| error category | input |
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
| audio duration | 120.00 s |
| processing_wall_seconds | 25.19 s |
| rtf | 0.210 |
| speedup | 4.764 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.53 s | 2.1 % | -0.54 s |
| capture_input | asr.submit.probe | 1 | ok | 0.34 s | 1.3 % | -0.49 s |
| other | worker_job | 1 | error | 4.18 s | — | +21.00 s |
| queue | · asr.queue_wait | 1 | ok | 21.00 s | 83.4 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 0.95 s | 3.8 % | +21.02 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +21.98 s |
| model_init | · vad.model | 1 | ok | 3.10 s | 12.3 % | +21.98 s |
| vad | · vad.speech_runs | 1 | ok | 0.09 s | 0.4 % | +25.08 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.00 s | 0.0 % | +25.18 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +25.18 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +25.18 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 0.00 s | 0 | — | — | — |

### Language checks

No language check was recorded.

### Primary passes

No primary pass was recorded.

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 120.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,453,053,440 B (2.28 GiB) → 2,599,002,112 B (2.42 GiB) |
| swap used | 1,291,948,032 B (1.20 GiB) → 1,291,890,688 B (1.20 GiB) |
| memory pressure | some_avg10=0.21 → some_avg10=0.14 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.08 s |
| telemetry buffer peak | 951 B |

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

- Top critical-path stages: queue 21.00 s (83.4 %); model_init 3.10 s (12.3 %); audio_prep 0.95 s (3.8 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: vad.model 3.10 s.
- Queue wait: 21.00 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Hypothesis: model loading takes 12.3 % of wall (cold model_init); keep models warm.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

Checked, did not fire: `asr_device_configured`, `swap_growth`.
