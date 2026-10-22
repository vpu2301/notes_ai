# Diagnostics — recording 00000000-0000-0000-0000-000000001000

Run `00000000-0000-0000-0000-000000002000` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 00000000-0000-0000-0000-000000001000 |
| processing_run_id | 00000000-0000-0000-0000-000000002000 |
| kind | initial |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

No model was used in this run.

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (not_measured) |
| processing_wall_seconds | — (unavailable) |
| rtf | — (not_measured) |
| speedup | — (not_measured) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| asr_primary | asr.transcribe_runs | 1 | ok | 50.00 s | — | +1.00 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

### Language checks

No language check was recorded.

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.transcribe_runs | — | — | 50.00 s | — |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | — (not_measured) |
| audio duration | — (not_measured) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | — (not_measured) |
| other model activity | none |
| telemetry overhead | — (not_measured) |
| telemetry buffer peak | — (not_measured) |

### Missing measurements

- **asr_primary**
  - asr.transcribe_runs: `audio_processed_seconds` (not_measured)
  - asr.transcribe_runs: `backend` (not_measured)
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
  - context: `run_context` (unavailable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (not_measured)
  - run: `concurrent_runs_at_start` (not_measured)
  - run: `processing_wall_seconds` (unavailable)
  - run: `rtf` (not_measured)
  - run: `speedup` (not_measured)
  - run: `telemetry_buffer_peak_bytes` (not_measured)
  - run: `telemetry_overhead_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 50.00 s (—).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: cold_model_init_share unavailable (unavailable) — rule `cold_model_init`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.
