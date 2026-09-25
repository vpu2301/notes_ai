# Notes eval baseline — 2026-09 (Summary Engine v2, Q1 → Q5)

> Q6 (closure, 3 runs, prompt `2026-10-12`): `notes-v2-closure-2026-09.md` — the Q6 pipeline report is now `notes-baseline-pipeline.json`.

Stack model `dev_mac` = `notes-chat` (Gemma 3 4B, Q4_K_M, Ollama) on the dev Mac. Corpus: the
committed synthetic set `tests/fixtures/eval/notes` (8 recordings for Q1/Q2; 10 for Q3, which
adds m09 voice memo and m10 interview). One run per arm.
`eval/notes/v2` (the bucket corpus with r01) was not mounted, so the Q2 acceptance numbers on the
real gold set are **still open**. Reports: `notes-{pipeline,single_pass}-2026-09-23-dev_mac-{q1,q2}.json` and
`notes-pipeline-2026-09-24-dev_mac-q3.json`, `notes-{pipeline,single_pass}-2026-09-24-dev_mac-q4.json`,
`notes-pipeline-2026-09-24-dev_mac-q5.json`; the nightly gate compares against
`notes-baseline-pipeline.json` (= the Q5 pipeline report).

| Metric | Q1 pipeline | Q2 pipeline | Q3 pipeline | Q4 pipeline | **Q5 pipeline** | Gate | Single-pass (Q1 / Q2 / Q4 run) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Unsupported lines | 0.419 | **0.000** | **0.000** | 0.000 | **0.000** | ≤ 0.02 | 0.714 / 0.714 / 0.786 |
| Invented claims | 4 | **0** | **0** | 0 | **0** | 0 | 10 / 5 / 17 |
| Example-phrase echo | 0 | **0** | **0** | 0 | **0** | 0 | 0 / 0 / 0 |
| Key-fact recall | 0.405 | **0.649** | **0.630** | 0.522 | **0.609** | ≥ 0.60 | 0.091 / 0.143 / 0.161 |
| Coverage ratio (worst ÷ best third) | 0.350 | **0.840** | **0.913** | 0.737 | **0.767** | ≥ 0.70 | 0.000 / 0.000 / 0.556 |
| Excluded speech | 0.332 | **0.000** | **0.000** | 0.000 | **0.000** | ≤ 0.02 | — |
| Recording-type accuracy | 0.667 | 1.000 | **0.900** | 0.900 | **0.900** | ≥ 0.95 | — |
| Redundancy | 0.338 | 0.269 | **0.050** | 0.051 | **0.046** | < 0.05 | — |
| Entity accuracy | 0.500 | 0.500 | **0.600** | 0.800 (knowable 1.000) | **0.800 (knowable 1.000)** | (Q4) | 0.500 / 1.000 / 0.500 |
| Hedge preservation | 0.000 | — (no hedged fact matched) | **0.000** | — | **0.000** | (Q4) | — |
| Attribution | — | — | **—** | — | **—** | (Q4) | — |
| Date resolution | — | — | **0.286** | 0.286 | **0.429** | unit set 100 % | — |
| Citation precision | 1.000 | 1.000 | **1.000** | 1.000 | **1.000** | — | — |
| Action F1 | 0.353 | 0.348 | **0.270** | 0.263 | **0.312** | — | 0.250 / 0.615 / 0.528 |
| Window failure rate | 0.125 | 0.125 | **0.100** | 0.000 | **0.000** | — | — |
| Lines cited | — | — | — | — | **1.000** | 100 % | — |
| Key-dates recall | — | — | — | — | **0.167** | — | — |
| Seconds per meeting-hour | 2 679 | 3 168 (+18 %) | **3 207** | 3 203 | **3 753** | ≤ +30 % | 281 / 392 / 371 |
| Meetings scored / failed | 8 / 0 | 8 / 0 | **10 / 0** | 10 / 0 | **10 / 0** | — | 3 / 5 · 3 / 5 · 6 / 4 |
| Judge: unsupported (17 lines) | — | 0.000 | **—** | — | **—** | — | — |
| Judge vs deterministic disagreement | — | 0.118 | **—** | — | **—** | > 0.02 → consider a production judge (after Q4) | — |

Regression checklists: `m06_de_news_podcast` (synthetic twin of the audit) **11/23 (Q1) → 14/23 (Q2) → 12/23 (Q3) → 18/23 (Q4) → 18/23 (Q5)**; `m09_en_voice_memo` 9/9 (Q3, Q5); `m10_de_interview` 7/10 (Q3) → 9/10 (Q5).

Reading it:

- The Q1 column is the audit reproduced: a third of the speech excluded on the model's say-so,
  42 % of composed lines unsupported, four invented claims. Q2 removes all three by code.
- **The single-pass baseline is not a usable comparison on this model**: Gemma 3 4B returns
  invalid JSON or runs out of context on 5 of 8 recordings; its 3 scored meetings are not the same
  set as ours. The blind pairwise comparison (Q4) needs a model that completes the baseline arm.
- m05 scored zero facts in both Q1 and Q2 runs: its only window's extraction came back as invalid
  JSON twice (a model failure, reported in `failed_ranges`, not a verification drop).
- m06 story 2 is only partly in the note (the union and the story are there; "3.000", the port
  cities and the delivery forecast are not) — recall on m06 is 3/11. The deterministic gate is not
  dropping it (`facts_dropped_paraphrase` 0, nothing excluded); the 4B model extracts few facts
  from long monologues. Kill criterion 1 is not triggered on these numbers, but m06 is the case
  to watch on the real corpus.
- Judge disagreement 0.118 = 2 of 17 lines where the deterministic check and the judge differ; the
  judge found no unsupported line. The sample is small; re-measure on `eval/notes/v2`.
- Numbers are one run each on a non-deterministic model; treat ±0.05 as noise.

Q3:

- **Recording type 0.90, gate 0.95 — not met.** Every type the author or template chose is right;
  of the three the classifier decided, m06 (podcast) and m07 (lecture) are right, m10 (a German
  interview) is read as a lecture. The first Q3 run was 0.80: the classifier listed "meeting"
  first and Gemma 3 4B took it for the podcast; listing it last (the Q1 rule for the context
  prompt) moved m06 from 0/3 to 3/3 in a classifier-only check. m10 stays wrong in either order —
  the model's limit, measured on 3 cases. Q4's kill criterion (< 0.85 → user selection only) is
  not triggered.
- **Redundancy 0.050, gate < 0.05 — not met: exactly at the limit.** All of it is m01 (4 of 9
  lines); every other recording is 0.
- **Date resolution 0.29 on the gold dates; the unit set is 100 %.** Dates are resolved only in
  the quotes of extracted facts, so a date whose fact was not extracted (m06 recall is 3/11)
  cannot score. The m06 checklist's dates fail for the same reason.
- m06 checklist 14 → 12: the two ASR-mangled names (Q4) and the "3.000"/port-city story detail
  (recall) fail; recording type now passes. Q2's 14 included `topics_min`, which Q3 turns off
  when a topic has one bullet — m06's facts no longer make two topics of two.
- Recall 0.65 → 0.63 and action F1 0.35 → 0.27 are inside run-to-run noise on one run of a
  non-deterministic 4B model; m09's four extracted actions against one gold action drive F1.

Q4 and Q5:

- **Redundancy 0.046, now under the 0.05 gate** (Q4 0.051). The first Q5 run read 0.131 because the
  scorer counted each key-date line as a repeat of the fact it dates; the scorer now leaves date
  lines out of redundancy and strips the date prefix before the invented-claim check (that run's
  12 "invented claims" were the same artifact). Only the re-run with the fixed scorer is kept.
- **Recording type still 0.90 against 0.95** — m10 is still read as a lecture. Unchanged since Q3.
- **Recall 0.52 (Q4) → 0.61 (Q5).** Q4 lost one fact on each of m02–m05; Q5 got them back with the
  quote-reminder retry (m09 no longer drops every fact for answering "[0]"). **m06 stays at 1/11
  in both** — the 4B model extracts few facts from the long news monologue. It is the main open
  quality risk and the case to measure on the real corpus.
- **Entity accuracy 0.80, 1.00 on the names that can be known.** The model tier is off
  (`MDX_NOTE_ENTITY_MODEL_TIER=false`): on m06 it respelled German nouns, 0 of 8 correct.
- **Hedge preservation 0.00** means one hedged gold fact was matched and it lost its hedge.
  Attribution is not scored because no gold fact that needs a holder was extracted.
- **Key-dates recall 0.17 and date resolution 0.43**: both are limited by extraction. A date is
  resolved only from the quote of a fact that was extracted.
- Lines cited 1.000: every written line has a row with a quote (Q5 T1).
- Time 3 753 s per meeting-hour, +17 % on Q3, within the +30 % budget. Q5 adds no model call; the
  difference is run-to-run noise on the dev Mac plus longer notes.
- The Q4 single-pass run fails 4 of 10 recordings, so the arms still can't be compared on the same
  set, and the blind pairwise rounds (3 raters) have not been held.
