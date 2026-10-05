# Speaker metrics — definitions (Sprint 30)

How well the diarizer's speakers survive contact with the people who read
them. Every number is a count or a ratio of counts on closed vocabularies;
nothing here reads a speaker name, a transcript or audio. Two sources:

- **Weekly cohort** — `scripts/ops/speaker_quality.sql`, run by
  `scripts/jobs/weekly_speakers.py` (`make weekly-speakers`, cron Monday
  06:30 UTC) as `funnel_reader`, which has a column-level grant (migration
  0046) and cannot read `speaker_names`, `speaker_name_candidates`,
  `previous_speaker_names` or `actor_sub`. Output: `speakers-YYYY-WW.csv`.
- **Live counters** — asr-service, on the "ASR Health" dashboard's Speakers
  row and behind the `SpeakerCorrectionRateHigh` alert.

## The caveat that applies to everything

**No edit = assumed correct.** A job nobody corrected is scored as right,
whether it was right, or wrong and nobody bothered, or wrong and nobody
noticed. So the correction rate is a **lower bound** on the real error
rate, and every accuracy-like number (exact count share, re-run success)
is an **upper bound**. Movement week over week is the signal; the level
is not a DER.

## Cohort

Complete jobs whose `metadata.diarization` is present (diarized), grouped
by the ISO week they **finished**, evaluated only once they finished more
than **7 days** ago — people get a week to correct a transcript before it
is scored. A job appears in the CSV once, in the report of the first
Monday after its 7 days, and again (unchanged unless edited later) in every
later report — the SQL recomputes all weeks each run.

**Opened** = `result_first_read_at` is set: the first successful
`GET /asr/jobs/{id}/result` by a client. note-service also reads that
endpoint when it builds a note from a transcript (automatically, after
every capture); it sends `X-MDX-Read-Purpose: note_build`, and such reads
set neither `result_first_read_at` nor `mdx_asr_diarized_results_opened_total`.
Most rates use opened jobs as the denominator.

## CSV columns

One row per `(week, dimension, bucket)`.

| Column | Definition |
|---|---|
| `week` | Monday of the ISO week the job finished |
| `dimension`, `bucket` | `all/all`; `engine/<metadata.diarization.engine>`; `hint/exact\|max\|none` (the request's speaker hint); `client/web\|ios\|macos\|other\|unknown` and `source/calendar_event\|manual\|upload\|other\|unknown` (`capture_context`, `unknown` = captured before Sprint 30); `count_confidence/high\|low\|unknown` |
| `diarized_jobs` | jobs in the cohort |
| `opened_jobs` | … of which opened |
| `corrected_jobs` | opened jobs with ≥ 1 **live** (not reverted) merge or reassign on any revision, or ≥ 1 re-run |
| `correction_rate_pct` | **speaker-correction rate** = corrected ÷ opened |
| `jobs_merged` / `jobs_reassigned` / `jobs_rediarized` | opened jobs with ≥ 1 live merge / live reassign / re-run |
| `merge_edits` / `reassign_edits` / `rediarize_runs` | **edit mix**: live merges, live reassigns, re-runs requested (sums) |
| `reverted_edits` | edits undone (`reverted_at` set) |
| `labels_created` | live reassigns that created a speaker the system missed (`creates_label`) |
| `count_scored_jobs` | opened jobs the count error is computed for (never re-run — see below) |
| `count_error_mean_abs` / `count_error_mean_signed` | mean \|count_error\| and mean count_error |
| `overcount_pct` / `undercount_pct` | share of scored jobs with count_error > 0 / < 0 (the rest: 0) |
| `rediarize_kept` | opened jobs re-run exactly once, successfully, not undone |
| `rediarize_kept_then_edited` | … of which still got live edits on the re-run's labels |
| `rediarize_undone` | re-run once, then undone |
| `rediarize_failed` | re-run once, never succeeded |
| `rediarize_repeated` | re-run two or more times |
| `rediarize_success_pct` | **re-run success** = kept ÷ jobs with ≥ 1 re-run |

**Confidence calibration** is the `count_confidence` rows: correction rate
for `low` should be clearly above `high`. If it is not, the roster guard's
word is not telling people anything.

## Approximations — each one, and why

1. **count_error = speakers_predicted − speakers_final, from edits only.**
   The final roster needs the segments (which label each turn ends up on),
   and the segments live in the encrypted transcript, not the database. From
   the edit overlay alone: `speakers_final = predicted − (distinct labels
   merged away) + (distinct labels created)`, so
   `count_error = merged_away − created` over live edits of revision 1.
   Missed: a label **emptied by reassigns** (every turn moved off it) still
   counts as present, so under-reported over-counts. A reassign to
   "unattributed" changes nothing here.
2. **Only never-re-run jobs are scored for count error.** A re-run
   overwrites `metadata.diarization` (and an undo does not restore it), so
   revision 1's `speakers` is gone for re-run jobs. `count_scored_jobs` says
   how many jobs the error is computed over; re-run jobs are in the re-run
   columns instead. Since people re-run the worst results, the scored set
   is biased towards easier recordings — another reason the count error is
   optimistic.
3. **"Live" edits.** Correction counts edits not reverted, on any revision.
   An edit that was applied and then undone is not a correction here; the
   live counter (`mdx_asr_speaker_corrected_jobs_total`) counts it — "a
   person started fixing it" — so the dashboard rate can be above the CSV's.
4. **Re-run success from `(diarization_runs, diarization_rev)`.** The
   schema keeps no per-run history (the report role cannot read
   `diarization_status`, and there is no per-run timestamp). A successful
   re-run and an undo each bump `diarization_rev`; a failed one does not.
   For a job re-run once this is exact: rev 2 = kept, rev 3 = undone, rev 1
   = failed (or, rarely, still running). Two or more re-runs are ambiguous,
   so they count as `rediarize_repeated` and never as success. The spec's
   "not undone or re-run **within 10 minutes**" becomes "ever, before the
   report" — stricter.
5. **Dimensions are the current revision's.** `engine`, `count_confidence`
   and the hint come from `metadata.diarization`, which a re-run replaces.
   For re-run jobs they describe the re-run.
6. **Hint** is `exact` when `hint_num_speakers` is set, `max` when only
   `hint_max_speakers` is, else `none`.

## Naming rate

Not in the CSV: whether a roster is fully named needs `speaker_names`,
which is content and deliberately not granted to the report role. The
naming signal is the live counter `mdx_asr_speaker_named_total{source}`
(`picklist` from calendar invitees vs `typed`) — a count of names set, not
a per-job "all labels named" rate. A per-job rate would need a count-only
column maintained by asr-service (e.g. `speakers_named_count`); until then
it is not measured.

## Live counters (asr-service)

| Metric | Meaning |
|---|---|
| `mdx_asr_diarized_results_opened_total` | +1 the first time a diarized job's result is opened |
| `mdx_asr_speaker_corrected_jobs_total` | +1 the first time a job gets a correction (first edit or first re-run) |
| `mdx_asr_speaker_edits_total{kind, action}` | `merge`/`reassign` × `apply`/`revert`; a reset carries `kind="all", action="reset"` |
| `mdx_asr_speaker_named_total{source}` | names set, `picklist` or `typed` |
| `mdx_asr_rediarize_total{outcome}` | re-runs finished by the worker (Sprint 29) |

Dashboard correction rate (7 d) =
`increase(corrected[7d]) / increase(opened[7d])`. The two increments happen
at different times for the same job (opened, then corrected later), so the
ratio of increases over a sliding window is close to, not equal to, the
cohort rate. `SpeakerCorrectionRateHigh` (warning) fires above 30 % with
≥ 50 opened jobs in the window — runbook
`docs/runbooks/asr-worker.md#speaker-correction-rate`.

## Targets

None set yet. The first weeks establish the baseline per engine; the
decision log (`docs/product/speaker-decisions.md`) records it.
