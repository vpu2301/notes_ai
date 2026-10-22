# Baseline `baseline-cpu`

**Status: not run. It waits on the recordings (`RECORDINGS.md`).** This file holds the protocol, the run plan and the threshold table for GATE A. The median and quality tables get filled from `evidence/A/baseline-cpu/runs.csv` and `quality.csv` by `compare.py` once the runs exist.

## Condition

Current code (`ce7f25a` + this sprint's harness, no pipeline change), current configuration: the asr-worker in the Docker Desktop container, faster-whisper `large-v3` int8 on CPU (see `EXISTING_RUNS.md`, "Environment").

## Protocol (reused by every sprint)

- Product path: `POST /asr/jobs` (language `auto`, diarize on, source `upload`), then `POST /v1/notes/from-transcript` when the job completes, then wait for `notes.generate` to close the run. That's the web's upload flow, minus the client events (F13).
- **Cold** ×2: `docker compose restart asr-worker` before each run. The job waits in the queue while the worker boots and loads `large-v3`; boot load is visible as `asr_model_startup_load_seconds`. The page cache is not dropped. **Warm** ×3 plus one discarded warm-up run (`excluded=warmup`).
- One job at a time: the harness waits until the caller has nothing queued or running. Afterwards it excludes any run with `concurrent_runs_at_start` > 0 (another workspace's job), `attempts` > 1, or a status other than `succeeded`. Excluded runs stay in `runs.csv` with the reason.
- Each row carries `execution_mode`, `memory_total_bytes`, `device` + `device_observation`, `app_commit` and the host's `memory_pressure` free %, so container and native runs can't be mixed up.
- Machine state to note during the runs: other apps closed; Docker Desktop VM memory setting (13.63 GiB is visible to the worker today); VM swap from each report.
- Medians with min/max per (recording, cold|warm); numbers come from the stored reports only.

## Run plan and expected duration

| Recording | Runs | Expected wall per run (CPU today) | Total |
|---|---|---|---|
| `de-2m`, `en-2m`, `uk-2m` | 2 cold + 4 warm each | ≈ 5–6 min | ≈ 1.7 h |
| `mix-de-en-3m` | 2 cold + 4 warm | ≈ 8 min | ≈ 0.8 h |
| `en-15m` | 2 cold + 4 warm | ≈ 36–40 min | ≈ 3.8 h |
| `de-15m` (optional) | 2 cold + 4 warm | ≈ 36–40 min | ≈ 3.8 h |

That's about 6.3 h without `de-15m`, run in the background. The stack must not take other jobs meanwhile; other sessions submitting 900 s jobs today would exclude runs.

```
uv run python tools/asr_bench/run_matrix.py --sprint A --condition baseline-cpu --recordings de-2m en-2m uk-2m mix-de-en-3m en-15m --cold --repeat 2
uv run python tools/asr_bench/run_matrix.py --sprint A --condition baseline-cpu --recordings de-2m en-2m uk-2m mix-de-en-3m en-15m --warm --repeat 3
# freeze references from warm run 1, then score every counted run against them:
uv run python tools/asr_bench/quality.py ref   --run-id <warm_1 run> --out ~/asr-perf-audio/refs/<id>.json
uv run python tools/asr_bench/quality.py score --run-id <run> --reference ~/asr-perf-audio/refs/<id>.json --sprint A --condition baseline-cpu --recording <id> [--switches …]
```

## Thresholds (§4, set before any change)

These are confirmed as written in the sprint. `compare.py` implements each one.

| Metric | Threshold for accepting a change | Note under pseudo-references (needs a gate decision) |
|---|---|---|
| WER per language (de, en, uk) | ≤ baseline + 1.0 pt and ≤ baseline × 1.10 | Baseline WER is 0 by construction, so "× 1.10" means *identical or fail*. **Proposal:** keep only "≤ + 1.0 pt" (1 % drift from the CPU transcript) |
| Language-switch recall (passages ≥ 3 s) | ≥ 90 % and ≥ baseline | Measured against your switch timestamps; unaffected |
| Short passages (< 3 s) | ≥ baseline; a translated passage is a failure | Unaffected |
| Word-timestamp error | median ≤ 80 ms, p90 ≤ 250 ms, ≤ baseline + 20 ms median | Measured as Δ against the baseline's own word times (baseline = 0), so 80 / 250 ms limits drift, not truth |
| Speaker attribution agreement | ≥ 95 % and ≥ baseline − 1 pt | Against the baseline's labels after the best mapping (baseline = 100 %) |
| Hallucinated segments | ≤ baseline | A candidate segment with no baseline word in its span; baseline = 0 |
| P1 speed (B2) | warm `asr_primary_rtf` ≤ 0.35; cold ≤ 0.6 including load | `asr_primary_rtf` excludes the model load (it happens at worker boot). **Proposal:** cold = (`asr_model_startup_load_seconds` + `asr_primary`) / audio |
| P1 memory | RSS ≤ baseline + 2 GB; swap delta ≤ 0.5 GB | RSS is the larger of the start/end samples; telemetry has no continuous peak |
| P2 speed (C2) | LID ≤ 3 % of audio and ≤ 10 s on `en-15m`; calls ≤ 1 + 2 × switches (mixed), ≤ 3 (mono); `time_to_asr_start` ≤ audio prep + 10 s | VAD alone took 31.6 s on the 900 s file and runs before ASR, so the literal "audio prep + 10 s" fails on VAD before LID matters. **Proposal:** audio prep + VAD + 10 s, with queue wait excluded |
| Combined (D) | warm `pipeline_wall / audio` ≤ 0.6 on `en-15m`, with diarization and quality checks on | Includes note generation (remote LLM, about 1.5–6.4 s per call) |
| Telemetry overhead | < 1 % | `telemetry_overhead_seconds / pipeline_wall` |

## Medians and quality

Pending the runs.
