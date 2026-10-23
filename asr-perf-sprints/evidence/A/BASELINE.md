# Baseline `baseline-cpu`

**Status: run 2026-10-23 on AC power, Low Power Mode off; waiting on GATE A.** This file holds the protocol, the run plan, the threshold table and the measured medians. Raw rows: `evidence/A/baseline-cpu/runs.csv` (speed), `quality.csv` (drift from the frozen reference), `quality_truth.csv` (against the TTS script). Run reports: `evidence/A/baseline-cpu/<recording>_<cold|warm>_<n>.md`.

## Condition

Current code (`ce7f25a` + this sprint's harness, no pipeline change), current configuration: the asr-worker in the Docker Desktop container, faster-whisper `large-v3` int8 on CPU (see `EXISTING_RUNS.md`, "Environment").

## Protocol (reused by every sprint)

- Product path: `POST /asr/jobs` (language `auto`, diarize on, source `upload`), then `POST /v1/notes/from-transcript` when the job completes, then wait for `notes.generate` to close the run. That's the web's upload flow, minus the client events (F13).
- **Cold** ×2: `docker compose restart asr-worker` before each run. The job waits in the queue while the worker boots and loads `large-v3`; boot load is visible as `asr_model_startup_load_seconds`. The page cache is not dropped. **Warm** ×3 plus one discarded warm-up run (`excluded=warmup`).
- One job at a time: the harness waits until the caller has nothing queued or running. Afterwards it excludes any run with `concurrent_runs_at_start` > 0 (another workspace's job), `attempts` > 1, or a status other than `succeeded`. Excluded runs stay in `runs.csv` with the reason.
- Each row carries `execution_mode`, `memory_total_bytes`, `device` + `device_observation`, `app_commit` and the host's `memory_pressure` free %, so container and native runs can't be mixed up.
- Machine state to note during the runs: other apps closed; Docker Desktop VM memory setting (13.63 GiB is visible to the worker today); VM swap from each report.
- **Power: AC only, Low Power Mode off.** On battery this Mac turns Low Power Mode on, which roughly halves CPU speed (ASR rtf ≈ 1.6–2.0 against ≈ 0.8–1.1 on AC). Each row records `power_source` and `low_power_mode`; the harness waits for AC before a run and excludes a run (`not_on_ac_power`) if the power log shows battery at any moment during it. The first baseline attempt (2026-10-22/23) ran almost entirely on battery and is kept apart as `evidence/A/baseline-cpu-battery/`; it is not the baseline.
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

All 25 counted runs (10 cold, 15 warm; the 5 warm-up runs are excluded) succeeded at attempt 1 with `concurrent_runs_at_start` 0, on AC with Low Power Mode off; `app_commit` `ce7f25a`, `inproc_cpu_asr`, large-v3 int8, `device` cpu (`observed`), `execution_mode` container. Median (min–max). One extra en-15m cold run replaces one that was cancelled when the Mac was unplugged a minute into it (kept in `runs.csv` as `status:cancelled`, report `en-15m_cold_1-cancelled.md`).

### Speed

"cold rtf incl. load" = (`asr_model_startup_load_seconds` + `asr_primary`) / audio, the proposed cold definition. "VAD+prep" = time to ASR start − queue wait − LID. Queue wait on cold runs is the worker boot (the job is submitted right after the restart).

| Recording | Temp | n | pipeline wall s | asr_primary s | asr rtf | cold rtf incl. load | LID calls | LID s | LID % audio | time to ASR start s | queue wait s | VAD+prep s | diarization s | RSS GB | swap Δ MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| de-2m | cold | 2 | 194 (192–197) | 93 (91–95) | 0.82 (0.80–0.84) | 0.91 (0.89–0.93) | 13 (13–13) | 63 (62–64) | 55 (54–57) | 82 (82–83) | 13 (12–14) | 5.9 (5.9–6.0) | 9 (9–9) | 2.79 (2.77–2.82) | 0.0 (0.0–0.0) |
| de-2m | warm | 3 | 224 (224–232) | 121 (118–129) | 1.06 (1.04–1.13) | – | 13 (13–13) | 84 (81–86) | 74 (72–76) | 88 (84–90) | 0 (0–0) | 3.1 (2.3–4.4) | 11 (8–13) | 2.90 (2.85–2.91) | 0.5 (0.0–9.4) |
| en-2m | cold | 2 | 202 (200–204) | 99 (98–99) | 0.87 (0.86–0.87) | 0.95 (0.94–0.95) | 15 (15–15) | 71 (70–72) | 63 (62–64) | 88 (87–89) | 11 (11–11) | 5.5 (5.5–5.6) | 7 (7–8) | 2.82 (2.76–2.89) | 0.0 (0.0–0.0) |
| en-2m | warm | 3 | 209 (206–242) | 113 (111–124) | 1.00 (0.97–1.09) | – | 15 (15–15) | 80 (78–101) | 71 (69–89) | 83 (80–106) | 0 (0–0) | 2.2 (2.0–5.4) | 7 (7–8) | 2.89 (2.88–2.89) | 18.7 (-0.1–21.8) |
| uk-2m | cold | 2 | 226 (216–236) | 122 (114–130) | 1.07 (1.00–1.14) | 1.15 (1.08–1.21) | 13 (13–13) | 66 (65–68) | 58 (57–59) | 81 (80–82) | 11 (10–11) | 4.1 (3.9–4.2) | 8 (7–8) | 2.89 (2.88–2.90) | 0.0 (0.0–0.0) |
| uk-2m | warm | 3 | 189 (188–193) | 105 (104–106) | 0.92 (0.91–0.93) | – | 13 (13–13) | 65 (63–67) | 57 (55–59) | 67 (65–70) | 0 (0–0) | 2.3 (2.2–3.0) | 7 (7–8) | 2.89 (2.89–2.89) | 0.3 (-0.1–42.2) |
| mix-de-en-3m | cold | 2 | 392 (359–425) | 204 (193–215) | 1.14 (1.08–1.20) | 1.21 (1.15–1.26) | 22 (22–22) | 130 (124–136) | 73 (69–76) | 148 (142–155) | 13 (13–13) | 5.7 (5.4–6.1) | 12 (11–13) | 2.83 (2.83–2.83) | 0.0 (0.0–0.0) |
| mix-de-en-3m | warm | 3 | 351 (313–353) | 192 (175–194) | 1.08 (0.98–1.09) | – | 22 (22–22) | 133 (115–134) | 74 (64–75) | 136 (118–138) | 0 (0–0) | 3.3 (3.2–3.6) | 11 (10–17) | 2.89 (2.89–2.90) | 5.0 (1.9–18.7) |
| en-15m | cold | 2 | 1195 (1160–1230) | 684 (663–705) | 0.77 (0.74–0.79) | 0.78 (0.76–0.80) | 79 (79–79) | 395 (377–413) | 44 (42–46) | 439 (424–455) | 15 (13–16) | 29.2 (27.8–30.6) | 53 (53–53) | 2.86 (2.84–2.89) | 11.1 (3.3–18.9) |
| en-15m | warm | 3 | 1303 (1275–1316) | 749 (734–764) | 0.84 (0.82–0.86) | – | 79 (79–79) | 455 (439–462) | 51 (49–52) | 471 (455–478) | 0 (0–0) | 16.1 (15.9–16.3) | 55 (54–56) | 2.25 (2.24–2.25) | 57.2 (34.2–78.3) |

Reading the speed table:

- **LID costs 42–76 % of the audio length, before ASR starts** (P2). It is one `large-v3` call per VAD speech run (13–22 calls on 2-minute files, 79 on en-15m). On en-15m the first transcript text comes 7–8 minutes after the job starts.
- **ASR** runs at 0.8–1.1 × audio (P1). The P1 targets (warm ≤ 0.35, cold ≤ 0.6) fail on every recording, as expected.
- **Cold vs warm** differs by the 23 s model load only; the asr/LID differences between the cold and warm rows are drift in the Mac's speed through the day (cold short runs 13:17–13:55, warm 16:00–18:40, after the long runs), not a warm-up effect. The spread within a group is 1–16 %.
- Memory: worker RSS 2.2–2.9 GB; swap Δ ≤ 80 MB.

### Quality: drift from the frozen reference (`quality.csv`)

The reference is warm run 1 of each recording (`quality.py ref`, kept in `~/asr-perf-audio/refs/<id>.json`, outside the repo). Every counted run, cold and warm, gives the identical transcript.

| Recording | n | WER % | CER % | ts median / p90 ms | speaker agreement | hallucinated | switches ≥3 s kept | <3 s kept |
|---|---|---|---|---|---|---|---|---|
| de-2m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0 (0–0) / 0 (0–0) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| en-2m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0 (0–0) / 0 (0–0) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| uk-2m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0 (0–0) / 0 (0–0) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| mix-de-en-3m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0 (0–0) / 0 (0–0) | 1.000 (1.000–1.000) | 0 (0–0) | 3/3 | 0/1 |
| en-15m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0 (0–0) / 0 (0–0) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |

### Quality: against the TTS script (`quality_truth.csv`)

The ground truth is the text `say` spoke (`~/asr-perf-audio/refs/<id>.truth.json`). It has segment times only, so its timestamp columns compare word times with segment starts and are **not a measure**; use the drift table for timestamps.

| Recording | n | WER % | CER % | ts median / p90 ms | speaker agreement | hallucinated | switches ≥3 s kept | <3 s kept |
|---|---|---|---|---|---|---|---|---|
| de-2m | 5 | 1.24 (1.24–1.24) | 0.14 (0.14–0.14) | 3397 (3397–3397) / 7230 (7230–7230) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| en-2m | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 2996 (2996–2996) / 6212 (6212–6212) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| uk-2m | 5 | 2.79 (2.79–2.79) | 0.72 (0.72–0.72) | 3978 (3978–3978) / 8638 (8638–8638) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |
| mix-de-en-3m | 5 | 2.51 (2.51–2.51) | 0.61 (0.61–0.61) | 2884 (2884–2884) / 6225 (6225–6225) | 0.835 (0.835–0.835) | 0 (0–0) | 3/3 | 0/1 |
| en-15m | 5 | 1.21 (1.21–1.21) | 0.31 (0.31–0.31) | 4448 (4448–4448) / 10785 (10785–10785) | 1.000 (1.000–1.000) | 0 (0–0) | – | – |

What the CPU baseline already loses, so a later sprint is not blamed for it:

- The short (1.39 s) English passage in mix-de-en-3m is not kept (0/1). The three long passages are (3/3).
- On mix-de-en-3m 16.5 % of words go to the wrong speaker.

### §4 checks on the baseline itself

`compare.py --a A/baseline-cpu --b A/baseline-cpu`: every quality check passes against itself (as it must). Every speed check fails on every recording: P1 warm/cold rtf, P2 LID ≤ 3 % of audio, LID calls, ASR start ≤ audio prep + 10 s. RSS, swap and telemetry overhead pass.
