# ASR performance sprints: log

## Sprint A: baseline (branch `perf/sprint-a-baseline`)

- 2026-10-22: Imported `~/Desktop/notes_telemetry.md` as `evidence/A/notes_telemetry_baseline.md`; verified it is content-free (timings, counts and fixed boilerplate only).
- 2026-10-22: Verified the pre-extracted run table against the stored run records and wrote `evidence/A/EXISTING_RUNS.md`. `f2e27fc8` is complete (wall 2307.34 s, `asr_primary` 1503.86 s, LID 54 / 597.60 s). Added the F3/F5 pair tables and fits: ASR chunk ≈ 8.31 s + 1.15 × audio; LID ≈ 11.2 s flat (r = −0.06).
- 2026-10-22: F13 investigated. Not a quick fix: the runs were submitted by a script (no preflight, `client` unavailable), so there are no start events, and display events arrive only when the note page is opened. F12's 70 min is the page-open time. Comparisons use `pipeline_wall` only.
- 2026-10-22: Owner decision: no hand-corrected references. Quality = drift against a frozen `baseline-cpu` transcript (`quality.py ref`), plus switch timestamps for the mixed file.
- 2026-10-22: Built `tools/asr_bench/` (`bench.py`, `run_matrix.py`, `quality.py`, `compare.py`), reusing the normalisation and WER from `scripts/eval/asr_scoring.py`. Wrote `tests/unit/test_asr_bench.py` (10 tests) with a trimmed `f2e27fc8` record as the fixture. Live smoke: a transcript scored against itself gives WER 0, and two CPU runs of the same file are identical.
- 2026-10-22: Fixed a WER mismatch in `quality.py`: the reference side used segment text, the hypothesis side word text. A run scored against itself gave 0.6 % until both sides used word text.
- 2026-10-22: No owner audio; the owner asked for the set to be found and made. Built it synthetically with macOS TTS (`make_tts_set.py`, scripts in `tts_set/`): de-2m, en-2m, uk-2m (≈ 114 s each), mix-de-en-3m (178 s, 3 English passages ≥ 3 s plus 1 of 1.4 s), en-15m (892 s, 4 speakers). Ground-truth text and spans go to `~/asr-perf-audio/refs/*.truth.json`.
- 2026-10-22: `run_matrix.py` now waits until the whole stack is idle (`telemetry_open_runs()` = 0), not just the caller's jobs. Another session was submitting 900 s jobs, and a cold restart would have killed its running job.
- 2026-10-22: Fixed a launch mistake: in zsh an unquoted `$R` does not split into words, so the first launch passed all ids as one name and exited at once.
- 2026-10-22: Three baseline launches, no run completed:
  1. 401: the token expired while waiting for another session's 900 s job. Fixed: log in on every idle poll.
  2. 400 `mime_not_allowed`: httpx sends `.flac` as `audio/x-flac`. Fixed: explicit browser MIME types.
  3. 17:55 UTC: right after my cold restart and submit, another session recreated `asr-service` and `asr-worker` (same images) with **`MDX_TELEMETRY_ENABLED=false`**, for its telemetry overhead runs (`telemetry-sprints/evidence/overhead/`). The harness's status poll died on the restart. I cancelled my job (`5e12a3b1`) so it wouldn't distort that session's measurement.
  **Baseline blocked:** two sessions share one dev stack with conflicting needs (theirs: telemetry off, back-to-back 900 s jobs; this one: telemetry on, an idle stack, worker restarts). The owner has to sequence them.
- 2026-10-22: Owner had the other session's 3600 s job (`90c8ada2`) cancelled; baseline started 20:33 UTC. 10 cold runs succeeded (all recordings × 2, `concurrent_runs_at_start` 0), committed as `fe8fa64`. A 401 mid-run on en-15m (token outlived) was fixed with re-login on 401 (`6323ffc`); the orphaned job was cancelled and en-15m restarted.
- 2026-10-23: Warm runs started 09:36 UTC; stopped 11:10 UTC after 14 rows. **The Mac was on battery with Low Power Mode on** (`pmset`: battery profile `lowpowermode 1`). Power log vs run times: only the two mix-de-en-3m cold runs (23:13–23:25 local) ran on AC; every other run so far was on battery. ASR rtf on AC ≈ 0.8–0.9; on battery/Low Power Mode ≈ 1.6–2.0. The power state is an uncontrolled variable in all of these runs, so they cannot be the baseline. The dev stack had also stopped overnight when the battery reached 10 % and the Mac slept.
- 2026-10-23: `run_matrix.py` now records `power_source` and `low_power_mode` per row and waits for AC power with Low Power Mode off before each run.
- 2026-10-23: Baseline rerun on AC power, Low Power Mode off (13:17–19:05 local): 10 cold + 15 warm counted runs, all attempt 1, no concurrency. The harness held the queue twice while the Mac was on battery (16 s at 13:32; 14:03–15:41) and one en-15m cold run that started on AC and then ran on battery was cancelled and replaced. References frozen from warm run 1; drift 0 on every run; against the TTS script WER 0–2.8 %. Medians in `BASELINE.md`.

## Observed, out of scope (not fixed here)

- F11: every finished job has redelivered-pickup `asr.queue_wait` spans (37 on `f2e27fc8`; one of them shows a 2,281 s "queue wait"). The visibility timeout is shorter than the job.
- F10: single worker, serial queue; `concurrent_runs_at_start` > 0 on 4 succeeded runs (`ebf66ca8`, `e3290649`, `f4eefbfc`, `8bdd3514`).
- `6c1b947a`: requeue after cancellation waited 1,379 s and then 1,684 s.
- F8: `dev_mac` / `notes-chat` reprocess failures (`error category: llm`).
- F7: diarization "Overlap with ASR: 0.00 s" is labelled "sequential" on some runs and "parallel" on others (one-line report fix allowed; not done yet).
- LID model: `effective_config.asr_lid_model` = `whisper-tiny`, but `lid.run` runs `large-v3` (input for C1).
- F6: `asr.model.startup_load_seconds` (24.35 s) is recorded but not printed in the report.
- Web uploads do not send `X-Client-Type` to asr-service, so `asr.submit.probe.client` is `unavailable` for web.
- The 2× spread in LID wall time across three identical 900 s runs (598 / 490 / 289 s) points to host load.
- `runs.csv` `rss_peak_bytes` is the larger of the two RSS samples a run records (start, end); telemetry has no continuous peak.
