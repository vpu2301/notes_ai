# Diagnostics — recording 78f2823c-3ce8-41e4-9bea-dfcd83f3c646

Run `83d1f157-04db-4fc2-99e2-241cc8e8c12f` · initial · succeeded

## 1. Run identity

| Field | Value |
|---|---|
| recording_id | 78f2823c-3ce8-41e4-9bea-dfcd83f3c646 |
| processing_run_id | 83d1f157-04db-4fc2-99e2-241cc8e8c12f |
| kind | initial |
| trigger | user |
| status | succeeded |
| error category | — |
| attempt | 1 |
| telemetry schema version | 1 |
| app commit | — (unavailable) |
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
| vad | — | silero-vad | — | — | — | cpu | observed |

## 2. End-to-end timing

| Metric | Value |
|---|---|
| audio duration | 90.00 s |
| processing_wall_seconds | 212.82 s |
| rtf | 2.365 |
| speedup | 0.423 |
| user_wait_seconds | — (not_measured) |
| time_to_transcript_seconds | — (not_measured) |
| time_to_speaker_labels_seconds | — (not_measured) |
| time_to_notes_seconds | — (not_measured) |

Wall time is the critical path; stage durations below are not additive where stages overlap.

## 3. Stage table

| Stage | Span | Attempt | Status | Duration | Share of wall | Start offset from submission |
|---|---|---|---|---|---|---|
| upload | asr.submit.upload | 1 | ok | 0.82 s | 0.4 % | -0.83 s |
| capture_input | asr.submit.probe | 1 | ok | 0.39 s | 0.2 % | -0.66 s |
| other | worker_job | 1 | ok | 212.73 s | — | +0.09 s |
| queue | · asr.queue_wait | 1 | ok | 0.06 s | 0.0 % | +0.04 s |
| audio_prep | · asr.audio_prep | 1 | ok | 1.16 s | 0.5 % | +0.11 s |
| model_init | · asr.model | 1 | ok | 0.00 s | 0.0 % | +1.27 s |
| model_init | · vad.model | 1 | ok | 2.80 s | 1.3 % | +1.27 s |
| vad | · vad.speech_runs | 1 | ok | 4.50 s | 2.1 % | +4.07 s |
| language_detection | · lid.recording | 1 | ok | 10.99 s | 5.2 % | +8.57 s |
| language_detection | · lid.run | 1 | ok | 13.06 s | 6.1 % | +19.58 s |
| language_detection | · lid.run | 1 | ok | 11.78 s | 5.5 % | +32.66 s |
| language_detection | · lid.run | 1 | ok | 11.17 s | 5.2 % | +44.46 s |
| language_detection | · lid.run | 1 | ok | 11.54 s | 5.4 % | +55.63 s |
| language_detection | · lid.run | 1 | ok | 10.33 s | 4.9 % | +67.18 s |
| asr_primary | · asr.transcribe_runs | 1 | ok | 119.14 s | 56.0 % | +77.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 18.37 s | 8.6 % | +77.51 s |
| asr_primary | · · asr.chunk | 1 | ok | 27.18 s | 12.8 % | +95.89 s |
| asr_primary | · · asr.chunk | 1 | ok | 26.35 s | 12.4 % | +123.08 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.73 s | 11.1 % | +149.45 s |
| asr_primary | · · asr.chunk | 1 | ok | 23.45 s | 11.0 % | +173.19 s |
| postprocess_cleanup | · asr.guards | 1 | ok | 0.02 s | 0.0 % | +196.65 s |
| postprocess_cleanup | · asr.prompt_echo | 1 | ok | 0.00 s | 0.0 % | +196.68 s |
| postprocess_cleanup | · asr.noise_markers | 1 | ok | 0.00 s | 0.0 % | +196.68 s |
| diarization_load | · diarization.load | 1 | ok | 4.25 s | 2.0 % | +196.68 s |
| diarization_infer | · diarization.infer | 1 | ok | 11.77 s | 5.5 % | +200.93 s |
| postprocess_attribute | · asr.speaker_attribution | 1 | ok | 0.00 s | 0.0 % | +212.70 s |
| postprocess_align | · asr.align | 1 | skipped | 0.00 s | — | +212.71 s |
| persist | · asr.persist | 1 | ok | 0.09 s | 0.0 % | +212.71 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +212.84 s |
| queue | · asr.queue_wait | 1 | ok | 212.80 s | — | +0.04 s |
| other | worker_job | 1 | skipped | 0.00 s | — | +212.85 s |
| queue | · asr.queue_wait | 1 | ok | 212.81 s | — | +0.04 s |

Spans under a redelivered pickup of a finished job are off the critical path.

## 4. ASR breakdown

### VAD

| Span | Speech | Runs | Min run | Median run | Max run |
|---|---|---|---|---|---|
| vad.speech_runs | 86.08 s | 5 | 9.41 s | 19.20 s | 19.20 s |

### Language checks

Language checks: 6.

| Span | Audio | Wall | Decided | Confidences |
|---|---|---|---|---|
| lid.recording | 86.08 s | 10.99 s | de | de 0.998, en 0.001, tr 0.000 |
| lid.run | 9.41 s | 13.06 s | de | de 0.995, en 0.002, it 0.000 |
| lid.run | 19.20 s | 11.78 s | de | de 0.998, en 0.001, it 0.000 |
| lid.run | 19.20 s | 11.17 s | de | de 0.998, en 0.001, ja 0.000 |
| lid.run | 19.20 s | 11.54 s | de | de 0.999, en 0.000, es 0.000 |
| lid.run | 19.09 s | 10.33 s | de | de 0.999, en 0.000, ja 0.000 |

### Primary passes

| Pass | Backend | Audio | Wall | rtf |
|---|---|---|---|---|
| asr.chunk | faster_whisper | 9.41 s | 18.37 s | 1.953 |
| asr.chunk | faster_whisper | 19.20 s | 27.17 s | 1.416 |
| asr.chunk | faster_whisper | 19.20 s | 26.35 s | 1.373 |
| asr.chunk | faster_whisper | 19.20 s | 23.73 s | 1.236 |
| asr.chunk | faster_whisper | 19.09 s | 23.45 s | 1.229 |

### Recovery passes

No recovery pass ran.

### Totals

| Metric | Value |
|---|---|
| asr_audio_processed_seconds (sum over passes) | 86.08 s |
| audio duration | 90.00 s |
| reprocessing ratio | 0.956 |

## 5. Diarization

| Step | Status | Seconds | State | Backend | Model | Device | Speakers | Unknown-speaker share |
|---|---|---|---|---|---|---|---|---|
| load | ok | 4.25 s | cold | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | — | — |
| infer | ok | 11.77 s | — | legacy-ecapa-ahc | spkrec-ecapa-voxceleb@0f99f2d | cpu (configured) | 1 | 0.0 % |

Overlap with ASR: 0.00 s (sequential).

## 6. LLM usage

No LLM call in this run.

## 7. Memory & resources, missing measurements

Telemetry for this run is incomplete.

| Resource | Value |
|---|---|
| process RSS | 2,442,072,064 B (2.27 GiB) → 3,049,246,720 B (2.84 GiB) |
| swap used | 712,880,128 B (0.66 GiB) → 709,349,376 B (0.66 GiB) |
| memory pressure | some_avg10=0.14 → some_avg10=1.06 |
| concurrent runs at start | 0 |
| other model activity | none |
| telemetry overhead | 0.30 s |
| telemetry buffer peak | 1,130 B |

### Missing measurements

- **audio_prep**
  - asr.audio_prep: `decrypt_seconds` (not_supported)
  - asr.audio_prep: `resample_seconds` (not_supported)
  - asr.audio_prep: `source_sample_rate_hz` (unavailable)
- **context**
  - context: `app_build` (unavailable)
  - context: `app_commit` (unavailable)
  - context: `chip_model` (not_supported)
  - context: `container_mem_limit` (unavailable)
  - context: `device_llm` (not_applicable)
- **diarization_load**
  - diarization.load: `speakers_detected` (not_applicable)
  - diarization.load: `unknown_speaker_share` (not_applicable)
- **model_init**
  - asr.model: `warmup_seconds` (not_applicable)
  - vad.model: `compute_type` (not_applicable)
  - vad.model: `model_revision` (unavailable)
  - vad.model: `quantization` (not_applicable)
  - vad.model: `warmup_seconds` (not_applicable)
- **postprocess_align**
  - asr.align: `duration_seconds` (not_applicable)
  - asr.align: `items` (not_applicable)
- **queue**
  - asr.queue_wait: `queue_depth_at_enqueue` (unavailable)
- **run**
  - run: `time_to_notes_seconds` (not_measured)
  - run: `time_to_speaker_labels_seconds` (not_measured)
  - run: `time_to_transcript_seconds` (not_measured)
  - run: `user_wait_seconds` (not_measured)

## 8. Bottleneck summary

### Measured

- Top critical-path stages: asr_primary 119.14 s (56.0 %); language_detection 68.88 s (32.4 %); diarization_infer 11.77 s (5.5 %).
- Reprocessing ratio: 0.956.
- Cold loads: vad.model 2.80 s; diarization.load 4.25 s.
- Queue wait: 0.06 s.
- LLM latency share of wall: no LLM call.
- UI delay (time_to_notes − processing_wall): — (time_to_notes_seconds not_measured).

### Hypotheses

- Hypothesis: diarization backend may be running on CPU — unverified (device_diarization is cpu, configured, not observed).

Checked, did not fire: `asr_device_configured`, `asr_dominates`, `reprocessing`, `cold_model_init`, `unknown_speakers`, `swap_growth`.
