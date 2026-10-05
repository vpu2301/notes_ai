# SQ2 coverage — the whole recording in the note, 2026-10-01

**Sprint:** SQ2 T6. **Verdict:** the kill rule applies. After two tuning iterations on the routed
model, key-fact recall is 0.18 against the 0.50 threshold. Prompt and window work on coverage
stops here, and the model bake-off is pulled forward (see Decision). **What did change:** facts now
come from later in a recording, and the note's sections follow its spoken structure. This is
true on r04 and r03 as well as on the synthetic set. **What the numbers cannot say:**

- There is no `eval/notes/v2` test split, because the owner decided against labelling (ADR-0068).
- There is no 60-minute recording in the corpus, and the goal is about 60-minute recordings.
- `hf_eu` exists only as a stand-in.

Every row is synthetic, or is one of two real recordings that have checklists but no key-fact gold.

**Diagnosis:** `docs/eval/sq2-diagnosis-2026-10-01.md`. H7 (the model lists the head of each
window) and H8 (the budget binds) hold on the routed model. H4 also holds on the `hf_eu` stand-in.
H1, H2, H3, H5 and H6 are ruled out.

## What was built

| Task | Change | Where |
|---|---|---|
| T1 | Per-window numbers in `stats.windows`, plus reduce input/cited, blocks planned/rendered and sections. Thirds are now **by time**: a whole window at its middle hid the head bias on one-window recordings | `pipeline.py`, `windows.third_of`, `scripts/eval/sq2_diagnose.py` |
| T2 | Extraction windows capped at 8,000 characters on long-context backends, with budgets scaled from that size. Small profile: `clamp(chars // 500, 8, 12)` facts per 6,000-character window | `windows.EXTRACT_WINDOW_CHARS`, `pipeline.small_budget` |
| T3 | Coverage guard. A third with ≥ 3 min of speech below 0.6 of the best third's facts per minute is re-read once from its own turns, with the coverage variant of the extraction prompt (time range plus the ids already found, no example). Still thin afterwards: `coverage_gaps` go into `failed_ranges` and the generation is `partial`, so the status line names the minutes. Lint rule `coverage.thirds` (F-COV, S2). A time budget skips the retry (`MDX_NOTE_COVERAGE_RETRY_BUDGET_S_PER_HOUR`, unset by default) | `pipeline.py`, `doclint.py`, `prompts.COVERAGE_SUFFIX`, `config.py` |
| T4 | Sections from the transcript, decided in three steps: (a) spoken chapter cues in de/en/uk; (b) otherwise a TextTiling lexical shift over 2-minute tiles; (c) the count reconciled to `round(D/4)` within [3, 8], with no part shorter than half an equal share. A part with fewer than two facts merges into its neighbour. Bullets stay in evidence-time order, and appended salient facts join the nearest part in time | `compose.segment`, `compose.blocks_at`, `classify.structure_cues` |
| T5 | Every block's facts reach its reduce call (no head truncation existed). Tests prove the last window's facts are cited in the last section, and that the small profile reads its last chunk | `test_meeting_doc_sq2.py` |
| T6 | Gates `sq2_gates` (recall, third ratio, sections band, near-empty, one-bullet sections, unsupported ≤ SQ1, p95 seconds on staging). Eval rows carry the SQ2 stats | `notes_scoring.py`, `notes_eval.py` |

**Deviations:**

- **Retry threshold.** The work order retries a third below 0.5 and lints below 0.6. The guard
  retries below 0.6, so no third is ever reported missing without having been read again; the lint
  hook has nothing left to do.
- **Prompt version.** `PROMPT_VERSION` 2026-10-01.2, with a matching routing waiver.

## Before and after, routed model (`mistral_eu`)

All rows ran on the same 13 recordings, one run each. Two identical runs differ by about 0.05 in
recall (SQ1 baseline note).

| Run | Code | Recall | Worst ÷ best third (recall) | Unsupported | Sections in band | One-bullet sections | Near-empty | Seconds per meeting-hour | Cents per meeting-hour |
|---|---|---|---|---|---|---|---|---|---|
| Before | SQ1 + T1 numbers | 0.12 | 0.44 | 0.14 | — | — | — | 603 | 14.3 |
| Iteration 1 | T2–T5 | 0.16 | 0.44 | 0.16 | 0.77 | 6 | 0.14 | 589 | 13.7 |
| Iteration 2 | + no part shorter than half an equal share | 0.18 | 0.67 | 0.15 | 0.92 | 4 | 0.29 ¹ | 490 | 11.3 |

¹ In this run r04 hit Mistral's rate limit (HTTP 429) on both windows and came out empty. Run on
its own, r04's note has 2 sections and 27 facts.

**Recall by language (synthetic m01–m11):**

| Run | en | de | uk |
|---|---|---|---|
| Before | 0.29 | 0.00 | 0.00 |
| Iteration 1 | 0.38 | 0.00 | 0.00 |
| Iteration 2 | 0.29 | 0.15 | 0.00 |
| `hf_eu` stand-in, before | 0.19 | 0.20 | 0.11 |

The German and Ukrainian notes are written in their own language (checked on the saved notes), so
the zeros are content, not a language bug.

**Where the facts come from, r04** (facts by third, by time):

| Run | Facts by third | First / second half of window 1 |
|---|---|---|
| Before | 12 / 5 / 2 | 17 / 2 |
| Iteration 1 | 14 / 3 / 9 | 14 / 2 |
| Iteration 2 (alone) | 16 / 3 / 8 | 18 split over two windows |

**r03 / r04 checklists** (`notes_assert.py`, Mistral):

| Run | r03 (of 40) | r04 (of 15) |
|---|---|---|
| Before | 30 | 6 |
| Iteration 1 | 26 | 7 |
| Iteration 2 | 24 | 6 |

r03 moves by ±3 between identical runs, so these are within noise. r04's newly passing item in
iteration 1 is "Kindergärten", from the recording's last third. Natanz, Homeland Justice and
Albanien stay missing. The r04 transcript is ASR output, and whether those names were transcribed
was not checked (content stays out of this page).

## The three recordings with the worst third ratio (iteration 2)

| Recording | Facts by third | Why |
|---|---|---|
| m06 news podcast (7 min) | 7 / 2 / 0 | One window. The model filled its 12-fact budget from the first two stories (H7, H8). Thirds are 2.3 min, below the guard's 3-minute floor, so the guard does not apply |
| m07 lecture (4.4 min) | 6 / 1 / 0 | Same: one window, head-listed, too short for the guard |
| r04 podcast (11.5 min audio, 8.4 min speech) | 16 / 3 / 8 | Two windows now, so the end is read. The middle stays thin: 2.7 min, again under the 3-minute floor |

**The guard did not fire once on this corpus.** Every third of every recording is under 3 minutes
of speech, except r04's first at 3.0. T3 is therefore proved by its unit tests only. On a 60-minute
recording each third has 20 minutes and the guard applies.

## Failure the eval surfaced: rate limits leave holes

`mistral_eu` answers HTTP 429 under this account's plan whenever two calls overlap, and sometimes
on its own. The provider raises `rate_limited` at once, and the window is lost. The engine then
behaves as specified: `failed_ranges`, a `partial` note, and a status line naming the minutes. But
it does so for a reason a retry with backoff would fix. This sits in `libs/models` (the provider),
outside SQ2's scope, and is listed under Decision.

## Time and cost

| | Before | After |
|---|---|---|
| Seconds per meeting-hour (Mistral, mean) | 603 | 490 |
| p95, per meeting | — | 2,134 (short synthetic meetings dominate) |
| Cents per meeting-hour | 14.3 | 11.3 |

Shorter windows cost no more on this corpus: more, smaller calls replace fewer, larger ones. The
SM-14 target (≤ 300 s per meeting-hour p95, staging) is not met by any backend measured. The guard's
time budget is therefore unset, because a limit now would switch the guard off everywhere.

## `hf_eu` stand-in

Before: recall 0.18, H4 and H7 held (table in the diagnosis). The after-run on the SQ2 code is
queued on the dev Mac behind the other local runs. A Gemma 3 4B run of these 13 recordings takes
hours on this machine, so its row is not in this report.

## Decision (kill rule)

Recall 0.18 < 0.50 and third ratio 0.67 < 0.80 after two iterations on the routed model:

1. **Stop prompt and window tuning for coverage.** The structural changes stay (T1–T5): they are
   correct on their own terms and tested, and they moved the end of r04 into the note.
2. **Pull the model bake-off forward** (Sprint 37 B-2) with SQ1's harness. On the same code,
   Mistral Large's pipeline recall (0.16–0.18) is below Gemma 3 4B at 32K (0.24 in SQ1). A
   single-pass call on Mistral recalls 0.36. The remaining loss is in what the pipeline keeps, not
   in which minutes it reads: F2/F3 strictness, per the SQ1 bisect.
3. **Before the bake-off:** a retry with backoff on HTTP 429 in the provider, so an eval measures
   the engine rather than the rate limit; and at least one 30–60-minute recording in the corpus,
   so T3 is exercised on real speech.
4. **Gates.** `PROMPT_VERSION` 2026-10-01.2 is not re-anchored as the nightly baseline (the gates
   do not hold).
