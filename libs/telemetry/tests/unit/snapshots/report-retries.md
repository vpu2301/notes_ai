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
| attempt | 2 |
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

| Kind | Backend | Name | Revision | Quantization | Compute type | Device | Device source |
|---|---|---|---|---|---|---|---|
| asr | whisper_cpp | whisper-large-v3 | edaa852 | int8 | int8 | metal | observed |
| diarization | pyannote | pyannote-3.1 | — | — | — | cpu | observed |
| llm | mistral_eu | mistral-large-2512 | — | — | — | remote | configured |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 200.00 s |
| processing_wall_seconds | 100.00 s |
| rtf | 0.500 |
| speedup | 2.000 |
| user_wait_seconds | 110.00 s |
| time_to_transcript_seconds | 101.00 s |
| time_to_speaker_labels_seconds | 101.50 s |
| time_to_notes_seconds | 108.00 s |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.40 s | 0.4 % | +0.00 s |
| other | worker_job | 1 | ok | 99.00 s | — | +0.50 s |
| queue | · asr.queue_wait | 1 | ok | 0.10 s | 0.1 % | +0.40 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.00 s | 1.0 % | +0.60 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +1.60 s |
| vad | · vad.speech_runs | 1 | ok | 2.00 s | 2.0 % | +1.60 s |
| language_detection | · lid.recording | 1 | ok | 4.00 s | 4.0 % | +3.60 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 70.00 s | 70.0 % | +7.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 35.00 s | 35.0 % | +7.60 s |
| asr_primary | · · asr.chunk | 1 | ok | 35.00 s | 35.0 % | +42.60 s |
| diarization_load | · diarization.load | 1 | ok | 2.00 s | 2.0 % | +77.60 s |
| diarization_infer | · diarization.infer | 1 | ok | 8.00 s | 8.0 % | +79.60 s |
| persist | · asr.persist | 1 | ok | 0.20 s | 0.2 % | +87.60 s |
| other | notes.generate | 1 | error | 2.00 s | — | +90.00 s |
| llm_call | · llm.note_write | 1 | error | 1.50 s | 1.5 % | +90.20 s |
| other | notes.generate | 2 | ok | 5.00 s | — | +93.00 s |
| llm_call | · llm.note_write | 2 | ok | 4.50 s | 4.5 % | +93.20 s |

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 90.00 s | 3 | 20.00 s | 30.00 s | 40.00 s |

### Language checks

Language checks: 1.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 90.00 s | 4.00 s | de | de 0.990, en 0.010 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | whisper_cpp | 45.00 s | 35.00 s | 0.778 |
| asr.chunk | whisper_cpp | 45.00 s | 35.00 s | 0.778 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 180.00 s |
| audio duration | 200.00 s |
| reprocessing ratio | 0.900 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 2.00 s | warm | pyannote | pyannote-3.1 | cpu (observed) | — | — |
| infer | ok | 8.00 s | — | pyannote | pyannote-3.1 | cpu (observed) | 3 | 5.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

| Purpose | Provider / model / backend | Attempt | Status | TTFT | Latency | Input | Cached | Reasoning | Output | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| note_write | mistral_eu / mistral-large-2512 / mistral_eu | 1 | error | — (not_applicable) | 1.50 s | 12,000 | 0 | 0 | — (error) | — (not_supported) |
| note_write | mistral_eu / mistral-large-2512 / mistral_eu | 2 | ok | — (not_applicable) | 4.00 s | 12,000* | 0* | 0* | 900* | — (not_supported) |
| **total** |  | 2 |  |  | 5.50 s | 24,000 | 0 | 0 | 900 |  |

Token accounting: estimated from characters (4 chars/token)

\* estimated, not reported by the provider.

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
  - asr.chunk: `beam_size` (not_measured)
  - asr.chunk: `chunk_count` (not_measured)
  - asr.chunk: `chunk_seconds` (not_measured)
  - asr.chunk: `compute_type` (not_measured)
  - asr.chunk: `device` (not_measured)
  - asr.chunk: `model` (not_measured)
  - asr.chunk: `segment_count` (not_measured)
  - asr.chunk: `word_count` (not_measured)
  - asr.transcribe_runs: `beam_size` (not_measured)
  - asr.transcribe_runs: `chunk_seconds` (not_measured)
  - asr.transcribe_runs: `compute_type` (not_measured)
  - asr.transcribe_runs: `device` (not_measured)
  - asr.transcribe_runs: `model` (not_measured)
  - asr.transcribe_runs: `segment_count` (not_measured)
  - asr.transcribe_runs: `word_count` (not_measured)
- **audio_prep**
  - asr.audio_prep: `decrypt_seconds` (not_measured)
  - asr.audio_prep: `resample_seconds` (not_measured)
  - asr.audio_prep: `source_sample_rate_hz` (not_measured)
  - asr.audio_prep: `target_sample_rate_hz` (not_measured)
- **context**
  - context: `container_mem_limit` (not_applicable)
- **diarization_load**
  - diarization.load: `audio_seconds` (not_measured)
  - diarization.load: `speakers_detected` (not_applicable)
  - diarization.load: `unknown_speaker_share` (not_applicable)
- **language_detection**
  - lid.recording: `duration_seconds` (not_measured)
- **llm_call**
  - note_write (attempt 1): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 1): `model_load_seconds` (not_applicable)
  - note_write (attempt 1): `output_tokens` (error)
  - note_write (attempt 1): `time_to_first_token_seconds` (not_applicable)
  - note_write (attempt 2): `generation_tokens_per_second` (not_supported)
  - note_write (attempt 2): `model_load_seconds` (not_applicable)
  - note_write (attempt 2): `time_to_first_token_seconds` (not_applicable)
- **model_init**
  - asr.model: `warmup_seconds` (not_measured)
- **queue**
  - asr.queue_wait: `enqueued_at` (not_measured)
  - asr.queue_wait: `queue_depth_at_enqueue` (not_measured)
  - asr.queue_wait: `started_at` (not_measured)
- **vad**
  - vad.speech_runs: `duration_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 70.00 s (70.0 %); diarization_infer 8.00 s (8.0 %); llm_call 6.00 s (6.0 %).
- Reprocessing ratio: 0.900.
- Cold loads: none.
- Queue wait: 0.10 s.
- LLM latency share of wall: 6.0 %.
- UI delay (time_to_notes − processing_wall): 8.00 s.

### Hypotheses


No rule fired.

Checked, did not fire: `asr_device_configured`, `diarization_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
