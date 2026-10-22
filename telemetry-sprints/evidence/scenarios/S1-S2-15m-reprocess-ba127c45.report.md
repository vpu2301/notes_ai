# Diagnostics — recording 7967deba-52de-45d6-a0e2-1356966ffc9c

Run `ba127c45-90e0-45a6-9a5b-df9575bb9713` · reprocess · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7967deba-52de-45d6-a0e2-1356966ffc9c |
| processing_run_id | ba127c45-90e0-45a6-9a5b-df9575bb9713 |
| kind | reprocess (notes) |
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

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | mistral_eu | mistral-large-2512 | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 14.68 s |
| rtf | — (unavailable) |
| speedup | — (unavailable) |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| llm_call | llm.provider_probe | 1 | ok | 0.57 s | 3.9 % | +0.32 s |
| other | notes.generate | 1 | ok | 13.79 s | — | +0.89 s |
| llm_call | · llm.note_write | 1 | ok | 13.57 s | 92.4 % | +0.97 s |

## 4. ASR breakdown

### VAD

No VAD span was recorded.

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
| audio duration | — (unavailable) |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

Diarization did not run.

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| provider_probe | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 0.57 s | 12 | 0 | 0 | 6 | — (not_supported) |
| note_write | openai_compat / mistral-large-2512 / mistral_eu | 1 | ok | — (not_applicable) | 13.57 s | 3,759 | 0 | 0 | 944 | — (not_supported) |
| **total** |  | 2 |  |  | 14.13 s | 3,771 | 0 | 0 | 950 |  |

Token accounting: OpenAI-compatible usage: prompt_tokens includes prompt_tokens_details.cached_tokens and completion_tokens includes completion_tokens_details.reasoning_tokens; all stored as reported, subsets never added again

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.05 s |
| telemetry buffer peak | 273 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
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
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `audio_duration_seconds` (unavailable)
  - run: `rtf` (unavailable)
  - run: `speedup` (unavailable)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: llm_call 14.14 s (96.3 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 96.3 %.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Not assessable: device_asr_observation unavailable (unavailable) — rule `asr_device_configured`.
- Not assessable: device_diarization_observation unavailable (unavailable) — rule `diarization_device_configured`.
- Not assessable: rtf unavailable (unavailable) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.
- Not assessable: unknown_speaker_share unavailable (not_applicable) — rule `unknown_speakers`.
- Not assessable: swap_delta_bytes unavailable (unavailable) — rule `swap_growth`.

No rule fired.

Checked, did not fire: `cold_model_init`.
