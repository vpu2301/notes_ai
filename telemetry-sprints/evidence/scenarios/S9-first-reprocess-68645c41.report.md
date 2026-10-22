# Diagnostics — recording 64eed3a7-cf18-47d2-b76f-3da80049ff91

Run `68645c41-b3a4-4d41-b517-411e2aa5ff2d` · reprocess · failed

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 64eed3a7-cf18-47d2-b76f-3da80049ff91 |
| processing_run_id | 68645c41-b3a4-4d41-b517-411e2aa5ff2d |
| kind | reprocess (notes) |
| trigger | user |
| status | failed |
| error category | llm |
| attempt | 3 |
| telemetry schema version | 1 |
| app commit | — |
| app build | — |

### Hardware & environment

No run context was recorded.

### Effective models & backends

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| llm | dev_mac | notes-chat | — | — | — | — | — |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | — (unavailable) |
| processing_wall_seconds | 55.50 s |
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
| llm_call | llm.provider_probe | 1 | error | 0.03 s | 0.1 % | +0.69 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +1.72 s |
| llm_call | llm.provider_probe | 1 | error | 0.01 s | 0.0 % | +3.74 s |
| llm_call | llm.provider_probe | 2 | error | 0.05 s | 0.1 % | +19.10 s |
| llm_call | llm.provider_probe | 2 | error | 0.01 s | 0.0 % | +20.16 s |
| llm_call | llm.provider_probe | 2 | error | 0.08 s | 0.1 % | +22.20 s |
| llm_call | llm.provider_probe | 3 | error | 0.04 s | 0.1 % | +52.41 s |
| llm_call | llm.provider_probe | 3 | error | 0.02 s | 0.0 % | +53.46 s |
| llm_call | llm.provider_probe | 3 | error | 0.01 s | 0.0 % | +55.48 s |

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
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.03 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.04 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.08 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 1 | error | — (not_applicable) | 0.04 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 2 | error | — (not_applicable) | 0.02 s | 8* | — | — | — | — (not_supported) |
| provider_probe | openai_compat / notes-chat / dev_mac | 3 | error | — (not_applicable) | 0.01 s | 8* | — | — | — | — (not_supported) |
| **total** |  | 9 |  |  | 0.27 s | 72 | — | — | — |  |

Token accounting: estimated: characters / 4 (the provider sent no usage object)

\* estimated, not reported by the provider.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| concurrent runs at start | 1 |
| other model activity | none |
| telemetry overhead | 0.27 s |
| telemetry buffer peak | 264 B |

### Missing measurements

- **context**
  - context: `run_context` (unavailable)
- **llm_call**
  - llm.provider_probe: `finish_reason` (unavailable)
  - llm.provider_probe: `http_status` (unavailable)
  - provider_probe (attempt 1): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 1): `completion_chars` (unavailable)
  - provider_probe (attempt 1): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 1): `model_load_seconds` (not_applicable)
  - provider_probe (attempt 1): `output_tokens` (unavailable)
  - provider_probe (attempt 1): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 2): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 2): `completion_chars` (unavailable)
  - provider_probe (attempt 2): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 2): `model_load_seconds` (unavailable)
  - provider_probe (attempt 2): `output_tokens` (unavailable)
  - provider_probe (attempt 2): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 2): `time_to_first_token_seconds` (not_applicable)
  - provider_probe (attempt 3): `cached_input_tokens` (unavailable)
  - provider_probe (attempt 3): `completion_chars` (unavailable)
  - provider_probe (attempt 3): `generation_tokens_per_second` (not_supported)
  - provider_probe (attempt 3): `model_load_seconds` (unavailable)
  - provider_probe (attempt 3): `output_tokens` (unavailable)
  - provider_probe (attempt 3): `reasoning_tokens` (unavailable)
  - provider_probe (attempt 3): `time_to_first_token_seconds` (not_applicable)
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

- Top critical-path stages: llm_call 0.28 s (0.5 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: — (not_measured).
- LLM latency share of wall: 0.5 %.
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
