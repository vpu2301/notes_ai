# ASR performance sprints: log

## Sprint A: baseline (branch `perf/sprint-a-baseline`)

- 2026-10-22: Imported `~/Desktop/notes_telemetry.md` as `evidence/A/notes_telemetry_baseline.md`; verified it is content-free (timings, counts and fixed boilerplate only).
- 2026-10-22: Verified the pre-extracted run table against the stored run records and wrote `evidence/A/EXISTING_RUNS.md`. `f2e27fc8` is complete (wall 2307.34 s, `asr_primary` 1503.86 s, LID 54 / 597.60 s). Added the F3/F5 pair tables and fits: ASR chunk ≈ 8.31 s + 1.15 × audio; LID ≈ 11.2 s flat (r = −0.06).
- 2026-10-22: F13 investigated. Not a quick fix: the runs were submitted by a script (no preflight, `client` unavailable), so there are no start events, and display events arrive only when the note page is opened. F12's 70 min is the page-open time. Comparisons use `pipeline_wall` only.
- 2026-10-22: Owner decision: no hand-corrected references. Quality = drift against a frozen `baseline-cpu` transcript (`quality.py ref`), plus switch timestamps for the mixed file.
- 2026-10-22: Built `tools/asr_bench/` (`bench.py`, `run_matrix.py`, `quality.py`, `compare.py`), reusing the normalisation and WER from `scripts/eval/asr_scoring.py`. Wrote `tests/unit/test_asr_bench.py` (10 tests) with a trimmed `f2e27fc8` record as the fixture. Live smoke: a transcript scored against itself gives WER 0, and two CPU runs of the same file are identical.
- 2026-10-22: Fixed a WER mismatch in `quality.py`: the reference side used segment text, the hypothesis side word text. A run scored against itself gave 0.6 % until both sides used word text.

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
