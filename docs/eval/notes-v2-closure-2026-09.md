# Summary Engine v2 — closure gates (Q6 T2), 2026-09-25

**Result: the sprint stops at T2.** Seven gates fail or cannot be computed;
nothing is deployed (T4 merge, T5, T6 staging stay open). One issue per failed
metric is drafted at the end.

**What was run.** Branch `engine-v2/Q1` at `2e02ef0` (Q1–Q5 + the T1
reconciliation), `PROMPT_VERSION 2026-10-12`. Stack model `dev_mac` = Ollama
`notes-chat` (Gemma 3 4B Q4_K_M) on the dev Mac; judge = the same model.
**Corpus: the synthetic set `tests/fixtures/eval/notes` (m01–m10), not
`eval/notes/v2`** — the real gold set and r01's transcript were not mounted,
and the maintainer runs them with a manual evaluation. Every number below is
superseded by the same table on `eval/notes/v2`.

- `make eval-notes BACKEND=dev_mac ARM=pipeline RUNS=3 JUDGE=dev_mac` →
  `notes-pipeline-2026-09-25-dev_mac-q6.json` (also the new
  `notes-baseline-pipeline.json`)
- `make eval-notes BACKEND=dev_mac ARM=single_pass RUNS=3` →
  `notes-single_pass-2026-09-25-dev_mac-q6.json`
- `make eval-notes-assert BACKEND=dev_mac` (m06, m09, m10; r01 has no
  transcript here)

The pipeline gave identical numbers in all three runs (temperature 0, same
prompts); the single-pass arm did not (it fails a different 4–6 of 10
recordings each run).

## The table (concept §3, Q5 gate)

| Metric | Q5 gate | Pipeline, mean of 3 | Result | Single-pass, mean of 3 |
|---|---|---|---|---|
| Unsupported lines | ≤ 1 % | 0.000 | **PASS** | 0.665 |
| Invented claims | 0 | 0 | **PASS** | 14.3 per run |
| Example-phrase echo | 0 | 0 | **PASS** | 0 |
| Key-fact recall | ≥ 90 % | 0.609 (28/46) | **FAIL** | 0.211 |
| Coverage ratio (worst ÷ best third) | ≥ 0.9 | 0.767 | **FAIL** | 0.433 |
| Excluded speech | ≤ 2 % | 0.000 | **PASS** | 0.000 |
| Recording-type accuracy | ≥ 95 % | 0.900 (9/10) | **FAIL** | 0.000 |
| Redundancy | < 5 % | 0.046 | **PASS** | 0.061 |
| Entity accuracy (name in glossary/calendar/candidates) | ≥ 97 % | 1.000 (all entities: 0.800) | **PASS** | 0.500 |
| Hedge preservation | 100 % | 0/1 | **FAIL** | — |
| Attribution | 100 % | no opinion/forecast/proposal gold line was extracted | **FAIL — not computable** | — |
| Date resolution (unit set) | 100 % | 100 % (`test_meeting_doc_q3.py`, `test_action_items*`); gold dates 0.429 | **PASS** | — |
| Blind pairwise vs single-pass (3 raters, ≥ 85 pairs) | ≥ 65 % | no round held; no `notes-pairs-*.json` | **FAIL — not computable** | — |
| Latency guardrail, p50, 60-min meeting, staging | ≤ +30 % | not run (no staging) | **FAIL — not run** | — |
| Lines cited (Q5) | 100 % | 1.000 | PASS | 0.000 |

Also measured: seconds per meeting-hour 3 300 / 3 804 / 3 424 (median 3 424 =
1.28 × the Q1 baseline 2 679; mean 3 509 = 1.31 ×) on the dev Mac, single-pass
374 median; meetings scored 10/10 per run, single-pass 4–6/10; action F1
0.312 (single-pass 0.483); citation precision 1.000; key-dates recall 0.167.

**Judge column.** 26 composed lines judged per run: `judge_unsupported_rate`
0.115 (3 lines, all `new_claim`), `deterministic_vs_judge_disagreement` 0.154.
The judge is the same 4B model that wrote the lines.

**Model entity tier.** `model_tier_precision` is not measured here (the tier
is off in the eval, as in production). The last measurement is Q4's: 0 of 8
respellings correct on m06.

**Cost per meeting-hour.** 0 — `dev_mac` is a local model with no price in
the `model_usage` ledger. Not measurable before a priced backend runs.

**Checklists.** m06 18/23 (failing: recording type, topics_min, two story
details, the hedge, one date), m09 9/9, m10 9/10 (recording type).
**r01: not run** — the audit transcript is not in this checkout; its
checklist (`assertions/r01_de_zeit_was_jetzt.assertions.json`) carries the
seven audit strings in `must_not_contain`.

## Reading it

- The faithfulness half of the initiative holds on every run: nothing
  unsupported, invented or echoed; nothing real excluded; every line cited.
  The single-pass baseline, on the same model, writes 67 % unsupported lines
  and ~14 invented claims per run and fails on half the recordings.
- **Recall is the whole gap, and it is one recording.** Without m06 (1 of 11
  key facts) recall is 27/35 = 0.77. m06 is a German news podcast of long
  monologues; the 4B model extracts ~7 facts from it. Coverage fails for the
  same reason (m06's first third: 0/4).
- The judge's 0.115 is 3 lines of 26 on a judge that is the model under
  test; it triggers ADR-0060's rule on this set, and it is the first thing
  to check by hand on `eval/notes/v2`.

## Issues (drafts — not opened)

One per failed metric, with the root-cause hypothesis and the sprint that
owned it. They are drafts because opening them publishes; the maintainer
opens the ones the real-set run confirms.

1. **key-fact recall 0.61 < 0.90** (Q2 owned the extraction budget; Q5
   gate). Hypothesis: the 4B model under-extracts from long single-speaker
   passages (m06 1/11; the rest 0.77). First step: the Sprint 37 tier
   bake-off on m06 and the real set — a model change, not an engine change
   (concept §8, first kill criterion's remedy).
2. **coverage ratio 0.77 < 0.9** (Q4). Hypothesis: same cause as 1 — m06's
   opening third yields no key fact. Re-measure after 1.
3. **recording-type accuracy 0.90 < 0.95** (Q3). One of three classifier
   decisions wrong: m10, a German interview, read as a lecture. Above the
   0.85 kill line. Hypothesis: a two-speaker Q&A with long answers looks
   like a lecture to the 4B model; the author's type picker covers it.
4. **hedge preservation 0/1 < 100 %** (Q4). m09's one hedged gold statement
   lost its hedge. Hypothesis: the voice-memo family writes the fact's text
   without `patch_claim`'s hedge prefix. Needs the line to confirm.
5. **attribution not computable** (Q4). No gold line that needs a holder was
   extracted on the synthetic set; measure on `eval/notes/v2`.
6. **blind pairwise not computable** (Q4/Q5). No rating round was held
   (3 raters, ≥ 85 pairs); sheets from `notes_pairs.py`.
7. **latency on staging not run** (Q6 T6). Dev-Mac median is 1.28 ×
   baseline, mean 1.31 ×; needs the staging scenario.
8. **production judge: rule triggered** (ADR-0060 decision 1). 0.115 − 0.000
   ≥ 0.02 on 26 lines, judged by the model under test. Confirm the three lines
   by hand and with a stronger judge on `eval/notes/v2` before building.
