# Diagnostics — recording 00000000-0000-0000-0000-000000001000

Run `00000000-0000-0000-0000-000000002000` · initial · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 00000000-0000-0000-0000-000000001000 |
| processing_run_id | 00000000-0000-0000-0000-000000002000 |
| kind | initial |
| trigger | user |
| status | failed |
| error category | asr |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | abc1234 |
| app build | 2026.10.22 |

### Hardware & environment

| Field | Value |
|---|---|
| OS | Darwin 25.4.0 |
| arch | arm64 |
| chip | Apple M5 |
| memory | 25,769,803,776 B (24.00 GiB) |
| execution mode | native |
| container limit | — (not_applicable) |

### Effective models & backends

No model was used in this run.

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 200.00 s |
| processing_wall_seconds | 20.50 s |
| rtf | 0.205 |
| speedup | 4.878 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| other | worker_job | 1 | error | 20.00 s | — | +0.50 s |
| asr_primary | · asr.transcribe_runs | 1 | error | 18.00 s | 87.8 % | +2.00 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.transcribe_runs | whisper_cpp | — | 18.00 s | — |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | 200.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 1,000,000,000 B (0.93 GiB) → 1,500,000,000 B (1.40 GiB) |
| swap used | 0 B (0.00 GiB) → 0 B (0.00 GiB) |
| memory pressure | normal → normal |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.04 s |
| telemetry buffer peak | 2,048 B |

### Missing measurements

- **asr_primary**
  - asr.transcribe_runs: `audio_processed_seconds` (not_measured)
  - asr.transcribe_runs: `beam_size` (not_measured)
  - asr.transcribe_runs: `chunk_count` (not_measured)
  - asr.transcribe_runs: `chunk_seconds` (not_measured)
  - asr.transcribe_runs: `compute_type` (not_measured)
  - asr.transcribe_runs: `device` (not_measured)
  - asr.transcribe_runs: `model` (not_measured)
  - asr.transcribe_runs: `segment_count` (not_measured)
  - asr.transcribe_runs: `wall_seconds` (not_measured)
  - asr.transcribe_runs: `word_count` (not_measured)
- **context**
  - context: `container_mem_limit` (not_applicable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 18.00 s (87.8 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.

No rule fired.

Checked, did not fire: `asr_device_configured`, `diarization_device_configured`, `asr_dominates`, `cold_model_init`, `swap_growth`.
