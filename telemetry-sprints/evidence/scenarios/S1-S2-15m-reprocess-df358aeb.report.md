# Diagnostics — recording 7967deba-52de-45d6-a0e2-1356966ffc9c

Run `df358aeb-a767-4e92-ba5a-4c833bf97b1c` · reprocess · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 7967deba-52de-45d6-a0e2-1356966ffc9c |
| processing_run_id | df358aeb-a767-4e92-ba5a-4c833bf97b1c |
| kind | reprocess (diarization) |
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
| diarization | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | — | — | — | cpu | configured |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 900.00 s |
| processing_wall_seconds | 107.22 s |
| rtf | 0.119 |
| speedup | 8.394 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| other | worker_job | 1 | ok | 107.19 s | — | +0.03 s |
| queue | · asr.queue_wait | 1 | ok | 0.02 s | 0.0 % | +0.01 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.13 s | 1.1 % | +0.03 s |
| diarization_load | · diarization.load | 1 | ok | 0.00 s | 0.0 % | +1.16 s |
| diarization_infer | · diarization.infer | 1 | ok | 105.63 s | 98.5 % | +1.16 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.31 s | 0.3 % | +106.81 s |
| persist | · asr.persist | 1 | ok | 0.08 s | 0.1 % | +107.12 s |

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
| audio duration | 900.00 s |
| reprocessing ratio | — (not_measured) |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 0.00 s | warm | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 105.63 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 5 | 9.7 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,343,591,936 B (2.18 GiB) → 2,393,894,912 B (2.23 GiB) |
| swap used | 1,054,547,968 B (0.98 GiB) → 1,054,081,024 B (0.98 GiB) |
| memory pressure | some_avg10=0.00 → some_avg10=0.00 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.05 s |
| telemetry buffer peak | 946 B |

### Missing measurements

- **audio_prep**
  - asr.audio_prep: `decrypt_seconds` (not_supported)
  - asr.audio_prep: `resample_seconds` (not_supported)
  - asr.audio_prep: `source_sample_rate_hz` (unavailable)
- **context**
  - context: `app_build` (unavailable)
  - context: `chip_model` (not_supported)
  - context: `container_mem_limit` (unavailable)
  - context: `device_llm` (not_applicable)
- **diarization_load**
  - diarization.load: `speakers_detected` (not_applicable)
  - diarization.load: `unknown_speaker_share` (not_applicable)
- **queue**
  - asr.queue_wait: `queue_depth_at_enqueue` (unavailable)
- **run**
  - run: `asr_audio_processed_seconds` (not_measured)
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: diarization_infer 105.63 s (98.5 %); audio_prep 1.13 s (1.1 %); postprocess_attribute 0.31 s (0.3 %).
- Reprocessing ratio: — (not_measured).
- Cold loads: none.
- Queue wait: 0.02 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).
- Not assessable: asr_primary_share unavailable (not_measured) — rule `asr_dominates`.
- Not assessable: reprocessing_ratio unavailable (not_measured) — rule `reprocessing`.

Checked, did not fire: `asr_device_configured`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
