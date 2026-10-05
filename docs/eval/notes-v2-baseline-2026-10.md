# Notes baseline after SQ1 — 2026-10-01

**Sprint:** SQ1 (transcript-summary-quality track). **Status:** synthetic only. These numbers
have no standing under the ADR-0068 routing rule, because `eval/notes/v2` holds no labelled
recordings. On 2026-10-01 the owner decided not to label a gold set for now (ADR-0068, "Owner
decision"). This page records two things. The first is what the synthetic set says about the arms. The second is where
the drop in recall since Q6 came from.

**Corpus:** `tests/fixtures/eval/notes` m01–m11. These are synthetic transcripts of 1 to 7
minutes in en, de and uk, with the v2 key facts. The bisect used the ten meetings m01–m10, so its
rows compare like with like. **Harness:** `scripts/eval/notes_eval.py`, with the D1 linter
applied as in the worker. **Runs:** one run per row. Two identical Mistral runs on the same day
differed by 0.06 in recall (0.18 and 0.12, SQ2 diagnosis), so a single row is good to about
±0.05.

## The arms on the synthetic set

| Arm | Model | Key-fact recall | Unsupported rate | Invented claims | Seconds per meeting-hour | Cost, cents per meeting-hour |
|---|---|---|---|---|---|---|
| Pipeline | `mistral-large-2512` (`mistral_eu`) | 0.16 | 0.21 | 17 | 737 | 17.25 |
| Single pass | `mistral-large-2512` | 0.36 | 0.33 | 23 | 89 | 1.35 |
| Pipeline | Gemma 3 4B, 32K, no small profile (the `hf_eu` stand-in) | 0.24 | 0.09 | 4 | 2,651 | local |
| Pipeline | Gemma 3 4B, 16K, no small profile | 0.13 | 0.11 | 4 | 2,524 | local |
| Pipeline | Gemma 3 4B, 16K, small profile (the dev default) | 0.17 | 0.16 | 4 | 2,439 | local |

Reports: `notes-pipeline-2026-10-01-mistral_eu-sq1-synthetic.json`,
`notes-single_pass-2026-10-01-mistral_eu-sq1-synthetic.json` and
`notes-pipeline-2026-10-01-dev_mac-sq1-now-{32k-noprofile,16k-noprofile,16k-profile}.json`.

**What it says.**

- **A larger model does not repair the pipeline.** Mistral Large writes a note with a lower recall
  than Gemma 3 4B at 32K, and with more unsupported lines.
- **A single call recalls more than the pipeline for a thirteenth of the cost**, but a third of its
  lines are unsupported. The pipeline's verification is what keeps unsupported lines down.
- **Context matters on the small model.** At 16K, recall falls from 0.24 to 0.13. The small-model
  profile wins back 0.04 at 16K.
- **No arm passes any §3 pilot gate.** The best recall is 0.36, against a 0.70 gate.

## Where the recall since Q6 went

The same ten meetings, on the same local model (`notes-chat-long`, Gemma 3 4B, 32K context, no
small-model profile), at successive commits on `engine-v2`. Each row is the code at that commit,
checked out in its own worktree and run on 2026-10-01.

| Commit | Sprint | Key-fact recall | Recall by third | Unsupported rate | Seconds per meeting-hour |
|---|---|---|---|---|---|
| `2e02ef0` | Q6 (reconciled) | **0.543** | 0.61 / 0.45 / 0.50 | 0.00 | 1,715 |
| `f04dfc9` | F2: statements, not quotes | 0.413 | 0.48 / 0.45 / 0.25 | 0.04 | 3,574 |
| `7759f84` | F3: figures, presenter, contact | **0.196** | 0.26 / 0.18 / 0.08 | 0.00 | 3,477 |
| `fe42e5e` | D1: the document linter | 0.196 | 0.30 / 0.18 / 0.00 | 0.19 | 5,215 |
| `1fccd93` | today (D2, L1, L2, SQ1) | 0.239 | 0.26 / 0.09 / 0.33 | 0.09 | 2,651 |

The F2 row was rerun at 32K on 2026-10-02 and replaces the historical 0.391, which came from the
F2 report of 2026-09-26 on `notes-chat`.

**Attribution.**

| Cause | Recall | Evidence |
|---|---|---|
| F2 (copies are evidence, restate once, no-information lines dropped) | −0.13 | Q6 → F2 |
| F3 (figures, presenter, contact follow-ups) | −0.22 | F2 → F3 |
| D1 and everything after it | about +0.04 | F3 → today, within run-to-run noise |
| The model | ruled out | Mistral Large on today's code scores 0.16 |
| Context, 32K → 16K | −0.11 | today's code at both sizes |
| Small-model profile at 16K | +0.04 | today's code with and without it |

**Reading.** The drop is in the code, and it falls in F2 and F3. Both sprints made the
verifier and the renderer stricter about what may become a line. F2 stores a copy of the
transcript as evidence and never writes it. F3 adds follow-up passes whose facts replace or
compete with statements. On a 4B model, much of what used to be written is now held back. The
linter and composition sprints (D1, D2) did not take recall away. They added unsupported lines,
which D2 then partly removed. The recall by third shows the same story: the last third falls
furthest (0.50 → 0.08 at F3). That is what SQ2 sets out to fix.

## What follows

- **ADR-0068.** There is no rule result, and staging stays on `hf_eu` under the waiver.
- **SQ2.** The coverage work starts from these numbers. Its diagnosis is
  `docs/eval/sq2-diagnosis-2026-10-01.md`.
- **F2 and F3.** Their strictness costs recall on the small model, and a revisit of their rules
  belongs to a later sprint. This page measures; it does not change them.
