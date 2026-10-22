# Existing runs: what "baseline-cpu" is today

Source: `notes_telemetry_baseline.md` (19 runs, collected 2026-10-22 15:24 UTC, commit `ce7f25a`), checked against the stored run records (`GET /v1/telemetry/runs/{id}`) on 2026-10-22 ~16:45 UTC. That includes a fresh export of `f2e27fc8`, which was still `running` at collection time. The numbers come from `tools/asr_bench/bench.py::row_from_run`. Content check of the imported file: the only non-table text is fixed report boilerplate ("Overlap with ASR …", "Token accounting …", "Spans under a redelivered pickup …"). It has no transcript, note or prompt text.

## Environment: what "baseline-cpu" means (F1, F2, F9)

| Fact | Value (identical on every initial run) |
|---|---|
| execution mode | `container` (Docker Desktop VM) |
| OS / arch | Linux `7.0.14-linuxkit` / `aarch64`; chip `not_supported` |
| memory visible to the worker | 14,636,097,536 B = **13.63 GiB** (the VM, not the 24 GB host) |
| ASR backend | `inproc_cpu_asr` = faster-whisper (CTranslate2), `large-v3` snapshot `edaa852e…`, `int8`, beam 5, device `cpu` **observed** |
| ASR model load | not in the run: loaded at worker boot. The `asr.model` span says `state: warm`, and its attribute `startup_load_seconds` = **24.35 s** (the report does not print it, F6) |
| language detection | `lid.run` uses the **`large-v3`** snapshot, although `effective_config.asr_lid_model` = `/opt/models/whisper-tiny` (input for C1) |
| VAD | silero, cold load 2.6–3.7 s per job |
| diarization | `legacy-ecapa-ahc` (`spkrec-ecapa-voxceleb@0f99f2d`), device `cpu` *configured only*; load 3.5–6.9 s when cold, 0 s when warm |
| memory state | RSS 2.2–3.1 GiB; **swap 0.6–1.1 GiB in use** in the VM; `some_avg10` up to 0.43 |

## Initial runs (verified)

`excl` applies the Sprint A protocol: only rows with `-` would enter a speed aggregate.

| Run | Audio s | Status | Queue s | LID calls / total s | ASR start +s | `asr_primary` s | ASR rtf | Diar load / infer s | Wall s | rtf | Concurrent | Attempts | excl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `83d1f157` | 90 | ok | 0.06 | 6 / 68.88 | 77.5 | 119.14 | 1.32 | 4.25 / 11.77 | 212.82 | 2.36 | 0 | 1 | - |
| `17846383` | 120 | ok | 0.03 | 7 / 75.35 | 80.5 | 185.24 | 1.54 | 0 / 16.46 | 324.24 | 2.70 | 0 | 1 | - |
| `2fa8e087` | 120 | ok | 24.23 | 6 / 63.66 | 97.5 | 171.68 | 1.43 | 3.93 / 13.20 | 297.03 | 2.48 | 0 | 1 | - |
| `ebf66ca8` | 120 | ok | 33.62 | 7 / 76.39 | 122.0 | 142.68 | 1.19 | 3.49 / 15.46 | 303.82 | 2.53 | 1 | 1 | concurrent |
| `e3290649` | 120 | ok | 280.50 | 7 / 67.31 | 351.5 | 153.49 | 1.28 | 0 / 16.91 | 537.85 | 4.48 | 1 | 1 | concurrent |
| `f4eefbfc` | 141.8 | ok | 14.12 | 8 / 75.43 | 97.2 | 198.70 | 1.40 | 3.91 / 19.10 | 319.15 | 2.25 | 1 | 1 | concurrent |
| `e608a97d` | 120 | partial (llm) | 0.02 | 7 / 87.74 | 94.1 | 176.31 | 1.47 | 3.48 / 15.14 | 521.97 | 4.35 | 0 | 1 | status |
| `2d702613` | 120 | failed (diarization) | 24.53 | 7 / 76.80 | 109.9 | 191.06 | 1.59 | 3.88 / error | 304.88 | 2.54 | 0 | 1 | status |
| `8bdd3514` | 120 | ok | 288.64 | 7 / 75.82 | 369.7 | 291.56 | 2.43 | 0 / 17.12 | 4918.44 | 40.99 | 1 (contended) | 1 | concurrent |
| `6c1b947a` | 141.8 | ok after cancel + 2 requeues | 1683.84 (attempt 3) | 8 / 81.59 (attempt 3; 16 / 170.45 over all attempts) | 1770.2 | 204.15 | 1.44 | 0 / 16.19 | 1990.62 | 14.04 | 0 | 3 | attempt>1 |
| `f2e27fc8` | 900 | ok (finished 15:45) | 21.83 | 54 / 597.60 | 656.1 | 1503.86 | 1.67 | 6.91 / 113.83 | 2307.34 | 2.56 | 0 | 1 | - |
| `351eccc5` | 900 | cancelled at +91 s | 0.02 | 5 / 54.19 | — | — | — | — | 91.62 | — | 0 | 1 | status |
| `2b4846f9`, `52f7bff1` | 120 | failed before ASR | 0.04 / 21.00 | 0 | — | — | — | — | 3.56 / 25.19 | — | 0 | 1 | status |

Differences from the pre-extracted table: `2d702613` has a stored rtf of 2.54 (shown as "—" in the pack); `6c1b947a`'s 16 / 170.45 counts all three attempts, while the final attempt alone is 8 / 81.59; `f2e27fc8` is now complete.

**Submitted after the collection** (same commit, same container config):

| Run | Audio s | Status | LID calls / total s | ASR start +s | `asr_primary` s | ASR rtf | Diar infer s | Wall s | rtf |
|---|---|---|---|---|---|---|---|---|---|
| `3203c1fc` | 900 | ok | 54 / 490.17 | 523.2 | 1541.33 | 1.71 | 58.85 | 2149.72 | 2.39 |
| `c1635f64` | 900 | running at check | 54 / 288.62 | 316.2 | — | — | — | — | — |

These are the same 54 checks with the same config, yet the LID total is 597.6 s, then 490.2 s, then 288.6 s. A 2× spread from host load alone is why the protocol records machine state and needs ≥ 3 warm repetitions.

**Usable for speed aggregates under the protocol:** `83d1f157`, `17846383`, `2fa8e087` (90–120 s files: `asr_primary` rtf 1.32–1.54, LID 6–7 calls / 64–75 s, wall 212–324 s) and `f2e27fc8`, `3203c1fc` (900 s: rtf 1.67–1.71, LID 490–598 s, wall 2150–2307 s, rtf 2.39–2.56). Every other run is excluded by status, attempt or concurrency.

## Baseline shapes B2 and C1 must change (from `f2e27fc8`)

Linear fit over the run's own spans:
- **ASR chunk:** wall ≈ **8.31 s + 1.150 × audio s** (r = 0.77). A fixed cost of about 8 s per chunk sits on top of roughly 1.15× real time.
- **LID check:** wall ≈ **11.24 s − 0.011 × audio s** (r = −0.06). The cost is flat and has no relation to fragment length: one full 30 s-window `large-v3` encoder pass per check.

- ASR chunks: n=61; audio < 5 s: median wall 12.37 s (n=17); audio = 30 s: median wall 40.97 s (n=12); Σ audio 866.14 s, Σ wall 1502.96 s
- LID checks: n=54; audio < 5 s: median wall 11.32 s (n=10); audio = 30 s: median wall 11.52 s (n=12); Σ audio 855.16 s, Σ wall 597.60 s

### ASR chunks (asr.chunk)

| # | chunk audio s | wall s | wall − audio s |
|---|---|---|---|
| 1 | 1.85 | 11.96 | +10.11 |
| 2 | 10.68 | 17.33 | +6.64 |
| 3 | 14.91 | 22.91 | +8.00 |
| 4 | 8.44 | 19.67 | +11.22 |
| 5 | 2.04 | 12.58 | +10.54 |
| 6 | 4.89 | 16.92 | +12.03 |
| 7 | 24.48 | 29.92 | +5.44 |
| 8 | 11.23 | 22.27 | +11.04 |
| 9 | 6.88 | 14.29 | +7.41 |
| 10 | 1.40 | 11.46 | +10.05 |
| 11 | 1.63 | 11.63 | +10.00 |
| 12 | 10.43 | 16.40 | +5.98 |
| 13 | 16.60 | 21.65 | +5.05 |
| 14 | 17.63 | 22.37 | +4.74 |
| 15 | 7.61 | 15.10 | +7.49 |
| 16 | 13.08 | 16.53 | +3.44 |
| 17 | 30.00 | 40.93 | +10.93 |
| 18 | 3.95 | 11.74 | +7.79 |
| 19 | 11.42 | 19.38 | +7.96 |
| 20 | 3.64 | 13.65 | +10.01 |
| 21 | 30.00 | 60.96 | +30.96 |
| 22 | 1.52 | 11.54 | +10.02 |
| 23 | 1.56 | 12.82 | +11.26 |
| 24 | 3.90 | 13.08 | +9.18 |
| 25 | 30.00 | 40.22 | +10.22 |
| 26 | 1.90 | 12.37 | +10.47 |
| 27 | 20.00 | 28.13 | +8.14 |
| 28 | 14.68 | 21.95 | +7.27 |
| 29 | 5.08 | 20.65 | +15.57 |
| 30 | 14.40 | 25.67 | +11.27 |
| 31 | 29.95 | 61.63 | +31.68 |
| 32 | 19.68 | 29.73 | +10.05 |
| 33 | 18.81 | 19.25 | +0.43 |
| 34 | 30.00 | 102.27 | +72.27 |
| 35 | 30.00 | 36.00 | +6.00 |
| 36 | 30.00 | 32.29 | +2.29 |
| 37 | 22.54 | 37.70 | +15.16 |
| 38 | 2.17 | 18.30 | +16.12 |
| 39 | 8.64 | 18.73 | +10.10 |
| 40 | 21.82 | 29.81 | +7.99 |
| 41 | 15.84 | 28.28 | +12.44 |
| 42 | 30.00 | 41.07 | +11.07 |
| 43 | 30.00 | 41.00 | +11.00 |
| 44 | 30.00 | 32.26 | +2.26 |
| 45 | 30.00 | 45.23 | +15.23 |
| 46 | 20.44 | 27.75 | +7.30 |
| 47 | 1.12 | 13.16 | +12.04 |
| 48 | 15.13 | 23.61 | +8.48 |
| 49 | 9.47 | 19.76 | +10.29 |
| 50 | 18.08 | 22.03 | +3.95 |
| 51 | 20.03 | 20.10 | +0.07 |
| 52 | 6.46 | 13.50 | +7.04 |
| 53 | 4.44 | 12.37 | +7.92 |
| 54 | 3.87 | 12.37 | +8.50 |
| 55 | 30.00 | 39.09 | +9.09 |
| 56 | 10.80 | 15.71 | +4.91 |
| 57 | 8.28 | 14.31 | +6.02 |
| 58 | 29.34 | 25.70 | -3.64 |
| 59 | 2.17 | 12.00 | +9.83 |
| 60 | 2.08 | 17.90 | +15.83 |
| 61 | 9.15 | 23.97 | +14.82 |

### Language checks (lid.run)

| # | fragment audio s | wall s | wall − audio s |
|---|---|---|---|
| 1 | 10.68 | 10.88 | +0.19 |
| 2 | 14.91 | 9.77 | -5.14 |
| 3 | 8.44 | 9.50 | +1.06 |
| 4 | 2.04 | 9.66 | +7.62 |
| 5 | 4.89 | 12.69 | +7.79 |
| 6 | 24.48 | 11.33 | -13.15 |
| 7 | 11.23 | 9.78 | -1.45 |
| 8 | 6.88 | 11.68 | +4.81 |
| 9 | 10.43 | 9.84 | -0.58 |
| 10 | 16.60 | 9.70 | -6.90 |
| 11 | 17.63 | 9.86 | -7.77 |
| 12 | 7.61 | 9.81 | +2.20 |
| 13 | 13.08 | 9.00 | -4.08 |
| 14 | 30.00 | 8.70 | -21.30 |
| 15 | 3.95 | 14.83 | +10.88 |
| 16 | 11.42 | 11.36 | -0.06 |
| 17 | 3.64 | 9.93 | +6.28 |
| 18 | 30.00 | 10.79 | -19.21 |
| 19 | 3.90 | 9.49 | +5.59 |
| 20 | 30.00 | 9.87 | -20.13 |
| 21 | 20.00 | 12.43 | -7.56 |
| 22 | 14.68 | 13.31 | -1.37 |
| 23 | 5.08 | 19.39 | +14.31 |
| 24 | 14.40 | 12.43 | -1.97 |
| 25 | 29.95 | 11.48 | -18.47 |
| 26 | 19.68 | 9.94 | -9.73 |
| 27 | 18.81 | 9.45 | -9.36 |
| 28 | 30.00 | 10.60 | -19.40 |
| 29 | 30.00 | 13.88 | -16.12 |
| 30 | 30.00 | 11.82 | -18.18 |
| 31 | 22.54 | 12.52 | -10.02 |
| 32 | 2.17 | 11.91 | +9.74 |
| 33 | 8.64 | 11.03 | +2.40 |
| 34 | 21.82 | 10.33 | -11.49 |
| 35 | 15.84 | 11.24 | -4.60 |
| 36 | 30.00 | 10.34 | -19.66 |
| 37 | 30.00 | 11.57 | -18.43 |
| 38 | 30.00 | 11.84 | -18.16 |
| 39 | 30.00 | 11.90 | -18.10 |
| 40 | 20.44 | 10.70 | -9.75 |
| 41 | 15.13 | 11.42 | -3.71 |
| 42 | 9.47 | 9.05 | -0.41 |
| 43 | 18.08 | 11.37 | -6.71 |
| 44 | 20.03 | 9.98 | -10.05 |
| 45 | 6.46 | 11.45 | +4.99 |
| 46 | 4.44 | 11.44 | +7.00 |
| 47 | 3.87 | 10.77 | +6.90 |
| 48 | 30.00 | 12.23 | -17.77 |
| 49 | 10.80 | 10.94 | +0.14 |
| 50 | 8.28 | 9.81 | +1.53 |
| 51 | 29.34 | 9.72 | -19.62 |
| 52 | 2.17 | 11.72 | +9.55 |
| 53 | 2.08 | 11.21 | +9.13 |
| 54 | 9.15 | 9.91 | +0.76 |

## Client events (F13): known gap, not a quick fix

Investigated on 2026-10-22:
- The web client is wired correctly. `MeetingPage` reports `upload_started` / `import_submitted` / `recording_stopped` and attaches them to the recording once the upload is accepted; `NoteEditorPage` reports the three `*_displayed` events. Ingest returns 202, and a run exists from submit onwards, so the events resolve to their run.
- The slow runs were **not submitted by a client.** Their `POST /asr/jobs` requests reached asr-service without a browser CORS preflight, and `asr.submit.probe.client` is `unavailable`. A script uploaded them, so no start event could exist.
- Display events arrive only when someone opens the note. `telemetry_client_events` holds 9 events for 5 runs; for example, `83d1f157`'s `transcript_displayed` arrived 7,798 s after submit, when the page was opened. **F12's "70.6 min gap" on `8bdd3514` is the same effect:** `time_to_transcript_seconds` (4,914 s) is when the note page was opened, not when the transcript became ready.
- The harness also submits through the API, without a client, so `user_wait_seconds` / `time_to_*` will stay `not_measured` for harness runs. **Decision:** comparisons use `pipeline_wall` only. User-visible timings would need a real client (web or macOS) to drive the run, which is outside this set.
- Side note for `LOG.md`: web uploads never send `X-Client-Type` to asr-service (`web/src/api/http.ts` sends it to the auth base only), so `client` is `unavailable` on web uploads too.
