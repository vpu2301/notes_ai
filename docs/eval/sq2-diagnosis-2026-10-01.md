# SQ2 diagnosis — why the note misses the middle and end, 2026-10-01

**Sprint:** SQ2 T1. **Question:** which of H1–H8 holds, on the routed model and on `hf_eu`.
**Code:** the engine as of SQ1 plus the T1 numbers only. Each window now records its
characters, budget, extracted, verified and kept-after-merge facts, call failure, and where in the
window its facts were said. The run used a snapshot of that code, so no SQ2 change is in these
tables. **Corpus:** synthetic m01–m11 (`tests/fixtures/eval/notes`) and the two real recordings
r03 and r04. Their transcripts stay in gitignored `scripts/eval/local/`; this page holds numbers
only. `eval/notes/v2` is empty (the owner's no-gold decision, ADR-0068), so there is no dev split.
**Backends:**

- **Routed model.** `mistral_eu` (`mistral-large-2512`, 128K context), which is the dev routing.
- **`hf_eu` stand-in.** Staging's `hf_eu` endpoint does not exist yet. Its stand-in is the same
  model family on the dev Mac: Gemma 3 4B (`notes-chat-long`) at 32K, without the small-model
  profile, which is `hf_eu`'s configuration.

**Tool:** `scripts/eval/sq2_diagnose.py`. The thresholds behind each verdict are fixed in the
script, before any run was read.

**Two hypotheses were added during T1:**

- **H7.** The model lists facts from the head of each window.
- **H8.** The window's fact budget binds, on any profile.

The work order's H1–H6 did not explain r04's symptom; these two do.

## Verdicts

| Hypothesis | Routed (`mistral_eu`) | `hf_eu` stand-in | Number it rests on |
|---|---|---|---|
| H1 later windows failed | ruled out | ruled out | 0 failed windows in thirds 2–3 on both. Rate limits later failed whole recordings; see the coverage report |
| H2 small-model profile starves long windows | ruled out | ruled out | neither backend is `small_model`; facts per character are constant. The dev Mac default *is* small-profile; T2 changed it anyway |
| H3 merge drops later facts | ruled out | ruled out | kept ÷ verified 1.00 (Mistral); 0.93 / 0.94 / 1.00 by third (Gemma) |
| H4 reduce cites only the head | ruled out | **held** | cited ÷ available by third 0.46 / 0.30 / 0.50 (Mistral) vs 0.37 / 0.32 / **0.14** (Gemma) |
| H5 noise exclusion removed content | ruled out | ruled out | largest excluded share 0.07 / 0.06 |
| H6 a one-section family | ruled out | ruled out | no recording ≥ 5 min with one block planned |
| **H7** head of the window | **held** | **held** | facts in windows' first / second half: 26 / 12 (Mistral), **31 / 3** (Gemma) |
| **H8** the budget binds | **held** | ruled out | 1 of 2 long windows returned its whole budget on Mistral. r04 returned 35 of 35, with 17 in the window's first half and 2 in its second |

**What happened on r04.** On Mistral, the 11-minute recording is a single 8,816-character
window, because 16,000-character windows hold it whole. The model listed facts in order and stopped
at the 35-fact budget before reaching the end. On Gemma, both windows show the same head bias,
and the reduce then cited none of the last third. Before T1, `facts_by_third` placed a whole
window at its middle, so a one-window recording showed every fact in "the middle third". That
was a measurement fault, now fixed: thirds are by time.

## Per-window tables

### mistral_eu · `mistral-large-2512` · context 131072 · small profile off

Report: `notes-pipeline-2026-10-01-mistral_eu-sq2-t1-mistral_eu.json` · prompt `2026-10-01` · git ``

| Recording | Min | Windows (chars) | Extracted (of budget) → verified → kept | 1st/2nd half | Failed | Facts by third | Cited by third | Recall by third | Blocks | Excluded |
|---|---|---|---|---|---|---|---|---|---|---|
| m01_en_product_sync | 1.1 | 1 (675) | 8 of 8→8→8 | 2/6 | 0 | 2 / 4 / 2 | 1 / 2 / 1 | 0/2 · 0/0 · 1/1 | 2 | 0.00 |
| m02_de_kundenprojekt | 0.9 | 1 (551) | 6 of 8→4→4 | 2/2 | 0 | 1 / 2 / 1 | 1 / 2 / 0 | 0/2 · 0/1 · 0/0 | 1 | 0.00 |
| m03_uk_planning | 0.9 | 1 (471) | 5 of 8→6→6 | 4/2 | 0 | 3 / 2 / 1 | 0 / 0 / 0 | 0/2 · 0/0 · 0/1 | 1 | 0.00 |
| m04_en_hiring | 0.9 | 1 (619) | 8 of 8→5→5 | 4/1 | 0 | 3 / 2 / 0 | 0 / 0 / 0 | 1/2 · 1/1 · 0/0 | 1 | 0.00 |
| m05_en_incident_review | 1.0 | 1 (689) | 8 of 8→8→8 | 5/3 | 0 | 3 / 5 / 0 | 2 / 1 / 0 | 0/3 · 0/0 · 0/0 | 2 | 0.00 |
| m06_de_news_podcast | 7.0 | 1 (3096) | 12 of 12→8→8 | 8/0 | 0 | 6 / 2 / 0 | 3 / 0 / 0 | 0/4 · 0/1 · 0/6 | 2 | 0.00 |
| m07_uk_lecture | 4.4 | 1 (1483) | 8 of 8→7→7 | 5/2 | 0 | 5 / 2 / 0 | 2 / 0 / 0 | 0/3 · 0/2 · 0/1 | 1 | 0.00 |
| m08_en_one_on_one | 2.3 | 1 (982) | 8 of 8→6→6 | 3/3 | 0 | 3 / 1 / 2 | 1 / 0 / 2 | 0/2 · 0/2 · 0/1 | 1 | 0.00 |
| m09_en_voice_memo | 2.5 | 1 (692) | 7 of 8→8→8 | 6/2 | 0 | 6 / 0 / 2 | 5 / 0 / 2 | 1/1 · 1/1 · 1/1 | 2 | 0.00 |
| m10_de_interview | 4.4 | 1 (1163) | 8 of 8→9→9 | 6/3 | 0 | 2 / 4 / 3 | 0 / 3 / 0 | 0/2 · 0/3 · 0/1 | 2 | 0.00 |
| m11_en_boat_walkthrough | 1.5 | 1 (988) | 8 of 8→11→11 | 5/6 | 0 | 3 / 6 / 2 | 0 / 0 / 0 | 0/1 · 0/0 · 0/3 | 2 | 0.00 |
| r03_de_palantir_podcast | 7.9 | 1 (8291) | 31 of 33→19→19 | 9/10 | 0 | 5 / 9 / 5 | 5 / 5 / 5 | 0/1 · 0/0 · 0/0 | 3 | 0.07 |
| r04_de_handala_podcast | 8.4 | 1 (8816) | 35 of 35→19→19 | 17/2 | 0 | 12 / 5 / 2 | 5 / 0 / 0 | 0/0 · 0/0 · 0/0 | 3 | 0.00 |

| Hypothesis | Verdict | Number |
|---|---|---|
| H1 | ruled out | 0 failed window(s) in thirds 2–3 (0 in all) |
| H2 | ruled out | backend is not small_model; facts per character are constant |
| H3 | ruled out | kept/verified by third: — / 1.00 / — |
| H4 | ruled out | cited/available by third: 0.46 / 0.30 / 0.50 |
| H5 | ruled out | largest excluded share of speech 0.07 |
| H6 | ruled out | 0 recording(s) ≥ 5 min with one block planned |
| H7 | held | facts in windows' first / second half: 26 / 12 |
| H8 | held | 1/2 windows of ≥ 4000 characters returned their whole budget |


### dev_mac · `notes-chat-long` · context 32768 · small profile off

Report: `notes-pipeline-2026-10-02-dev_mac-sq2-t1-hfeu-standin.json` · prompt `2026-10-01` · git ``

| Recording | Min | Windows (chars) | Extracted (of budget) → verified → kept | 1st/2nd half | Failed | Facts by third | Cited by third | Recall by third | Blocks | Excluded |
|---|---|---|---|---|---|---|---|---|---|---|
| m01_en_product_sync | 1.1 | 1 (675) | 8 of 8→8→8 | 6/2 | 0 | 5 / 1 / 2 | 4 / 1 / 1 | 1/2 · 0/0 · 0/1 | 2 | 0.00 |
| m02_de_kundenprojekt | 0.9 | 1 (551) | 6 of 8→6→6 | 3/3 | 0 | 2 / 2 / 2 | 2 / 1 / 1 | 0/2 · 0/1 · 0/0 | 1 | 0.00 |
| m03_uk_planning | 0.9 | 1 (471) | 8 of 8→9→9 | 6/3 | 0 | 4 / 5 / 0 | 3 / 4 / 0 | 1/2 · 0/0 · 0/1 | 2 | 0.00 |
| m04_en_hiring | 0.9 | 1 (619) | 8 of 8→7→7 | 5/2 | 0 | 4 / 3 / 0 | 2 / 0 / 0 | 1/2 · 0/1 · 0/0 | 1 | 0.00 |
| m05_en_incident_review | 1.0 | 1 (689) | 6 of 8→5→4 | 3/2 | 0 | 2 / 1 / 1 | 0 / 0 / 0 | 1/3 · 0/0 · 0/0 | 1 | 0.00 |
| m06_de_news_podcast | 7.0 | 1 (3096) | 11 of 12→11→10 | 5/6 | 0 | 2 / 6 / 2 | 0 / 3 / 0 | 0/4 · 1/1 · 1/6 | 2 | 0.02 |
| m07_uk_lecture | 4.4 | 1 (1483) | 8 of 8→8→5 | 6/2 | 0 | 4 / 1 / 0 | 0 / 0 / 0 | 0/3 · 0/2 · 0/1 | 1 | 0.00 |
| m08_en_one_on_one | 2.3 | 1 (982) | 8 of 8→7→7 | 5/2 | 0 | 5 / 2 / 0 | 5 / 2 / 0 | 0/2 · 0/2 · 0/1 | 1 | 0.00 |
| m09_en_voice_memo | 2.5 | 1 (692) | 8 of 8→2→2 | 2/0 | 0 | 2 / 0 / 0 | 2 / 0 / 0 | 0/1 · 0/1 · 0/1 | 1 | 0.00 |
| m10_de_interview | 4.4 | 1 (1163) | 8 of 8→7→7 | 7/0 | 0 | 5 / 2 / 0 | 0 / 0 / 0 | 1/2 · 1/3 · 0/1 | 1 | 0.00 |
| m11_en_boat_walkthrough | 1.5 | 1 (988) | 8 of 8→8→8 | 3/5 | 0 | 3 / 4 / 1 | 3 / 0 / 0 | 1/1 · 0/0 · 0/3 | 2 | 0.00 |
| r03_de_palantir_podcast | 7.9 | 2 (4488, 3907) | 14 of 17→13→11 · 15 of 15→12→12 | 12/1 · 12/0 | 0 | 10 / 9 / 4 | 3 / 1 / 0 | 0/1 · 0/0 · 0/0 | 3 | 0.06 |
| r04_de_handala_podcast | 8.4 | 2 (4481, 4349) | 17 of 17→17→17 · 9 of 17→4→4 | 17/0 · 2/2 | 0 | 17 / 2 / 2 | 0 / 0 / 0 | 0/0 · 0/0 · 0/0 | 3 | 0.00 |

| Hypothesis | Verdict | Number |
|---|---|---|
| H1 | ruled out | 0 failed window(s) in thirds 2–3 (0 in all) |
| H2 | ruled out | backend is not small_model; facts per character are constant |
| H3 | ruled out | kept/verified by third: 0.93 / 0.94 / 1.00 |
| H4 | held | cited/available by third: 0.37 / 0.32 / 0.14 |
| H5 | ruled out | largest excluded share of speech 0.06 |
| H6 | ruled out | 0 recording(s) ≥ 5 min with one block planned |
| H7 | held | facts in windows' first / second half: 31 / 3 |
| H8 | ruled out | 1/3 windows of ≥ 4000 characters returned their whole budget |


**Reading the tables.**

- **Extracted (of budget).** What the model returned against what it was allowed.
- **1st/2nd half.** Verified facts said in the first and second half of the window's time span.
- **Facts / cited by third.** By the fact's own time, across the recording.
- **Recall by third.** Gold key facts found, as found / total. r03 and r04 have no key-fact gold,
  only checklists.

## Dev Mac default (small-model profile), added 2026-10-02

The dev default is Gemma 3 4B at 16K with the small-model profile (`small_model: true`, a fixed
12 facts per window). It is not a routed staging backend. This run shows what the profile does to
coverage.

| Hypothesis | Verdict | Number |
|---|---|---|
| H2 small profile starves long windows | ruled out at the 50 % threshold | 6 of 15 windows filled the fixed 12 |
| H4 reduce cites only the head | held | cited ÷ available by third 0.32 / 0.26 / 0.52 |
| H6 one-section family | held | 1 recording ≥ 5 min with one block planned |
| H7 head of the window | **held** | first / second half 28 / 2 |
| H8 the budget binds | **held** | 3 of 3 windows ≥ 4,000 characters returned their whole budget |

H1, H3 and H5 are ruled out. The fixed twelve binds on every long window, which is T2's
`small_budget` case even though H2's share-of-all-windows test stays under its threshold. The full
table is `notes-pipeline-*-dev_mac-sq2-t1-devmac-profile.json`.

## What T2–T5 do with this

- **H7 and H8 (head of window, budget binds).** Two tasks address them:
  - **T2** caps extraction windows at 8,000 characters on long-context backends. On the small
    profile, the budget follows the window's length. So a long recording gets more, shorter
    windows. T2 was kept because H7/H8 hold on the routed model; H2 alone would have skipped it.
  - **T3** re-reads a third that came out thin, using its own turns.
- **H4 (Gemma's reduce drops the last third).** T4 cuts blocks from the transcript, not from where
  facts cluster. T5's reduce already receives every fact of a block; the tests now prove it,
  including the last chunk under the small profile.
- **H1, H3, H5, H6.** Ruled out on both backends. Nothing was changed for them.

The results are in `docs/eval/sq2-coverage-2026-10-01.md`.
