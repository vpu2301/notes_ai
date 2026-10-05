# ADR-0060 — Summary Engine v2 closure: judge, entity tier, what stays out

**Status:** Accepted · **Date:** 2026-09-25 · **Amends:** ADR-0058

## Context

Summary Engine v2 (sprints Q1–Q5, `docs/sprints/summary-engine-v2/`) rebuilt
the document engine after the 2026-09-22 audit: every line cited and
supported by code, noise confirmed by code, recording types, names and
hedges, one row per written line. Two decisions were deferred to the
closure sprint (Q6) and are to be made from numbers:

1. whether a model judge runs in production next to the deterministic
   support check;
2. whether the model entity tier (`MDX_NOTE_ENTITY_MODEL_TIER`, Q4) runs in
   production.

The numbers come from `docs/eval/notes-v2-closure-2026-09.md`: three runs
of the pipeline arm and the single-pass arm with the stack model (`dev_mac`,
Gemma 3 4B) on the **synthetic** corpus `tests/fixtures/eval/notes`
(m01–m10). The real gold set `eval/notes/v2` and the blind pairwise rounds
were not available for this run; the maintainer runs them on the real set
with a manual evaluation. Every decision below names the number that would
reverse it on that set.

## Decision

1. **Production judge: rule triggered on the synthetic set; not built in
   Q6.** Rule: build it only if `judge_unsupported_rate − unsupported_rate ≥
   0.02` (the deterministic gate misses at least 2 % of lines a judge
   catches). Measured on m01–m10, 3 runs: 0.115 − 0.000 = 0.115 — 3 of 26
   composed lines flagged `new_claim`, identical in every run — with the
   judge being the same Gemma 3 4B model that wrote the lines. That is
   enough to take the question seriously and not enough to add a model call
   to every generation: a production judge is a new model call, which Q6
   rules out of scope, and the concept's NOT NOW keeps it "eval instrument
   first". The decision is therefore made on `eval/notes/v2`: check the
   flagged lines by hand, re-run the judge column with a judge stronger than
   the model under test, and build the judge (its own sprint) if the rule
   still holds. Until then it stays an eval column (`--judge`). Also
   revisit when the weekly notes-quality report shows dismissals with reason
   `not_said` above 5 % of written lines.
2. **Entity model tier: off in production, on in staging.**
   `infra/k8s/notes/values-prod.yaml` sets `MDX_NOTE_ENTITY_MODEL_TIER:
   "false"`; `values.yaml` (staging) sets `"true"` so the tier is measured
   on real recordings. Rule: production only when `model_tier_precision ≥
   0.9` on `eval/notes/v2`. Measured: not in the closure run (the tier is off
   in the eval, as in production); the last measurement, Q4 on m06, was 0 of 8
   respellings correct — it respelled German nouns that were not names.
   The glossary and known-people tier (a) stays on everywhere.
3. **The initiative stops at the closure gates, not after them.** On the
   synthetic set the faithfulness gates pass (unsupported, invented, echo,
   excluded speech, redundancy, entities, date unit set) and seven do not
   (recall, coverage, recording type, hedges, attribution, blind pairwise,
   staging latency) — `docs/eval/notes-v2-closure-2026-09.md`, with one issue
   draft per metric. Per the sprint's stop rule nothing is deployed until the
   same table on `eval/notes/v2` passes. No further engine feature is
   started without a named failing metric from that table or from the weekly
   notes-quality report; the four-week production read (kept-line rate,
   regenerate rate, share-without-edit against the concept's thresholds) is a
   calendar entry, not a sprint.

**NOT NOW** (concept §8, carried forward verbatim as the closing state):

- Positions map (P2-4). No evidence users ask for it; needs disagreement detection we cannot verify.
- External entity enrichment (P2-8). Sends recording content to a third party; egress allowlist forbids it; no consent model exists.
- A production LLM judge. Eval instrument first (decision 2 in the README).
- Wikidata / web lookup for names. Same egress reason; glossary + calendar + bounded model correction first.
- Sound-bite (quoted clip) detection as a diarization feature. Q4 does the cheap heuristic only.
- Fine-tuning on corrections. They feed glossary, eval and prompts.
- Changing the note's template at generation time. The template is a home for sections, not a heading; only the label changes (Q3).
- Live in-meeting summaries; auto-sending anything; a second LLM client library.

## Reconciliation with ADR-0059 (Q6 T1)

- **One title mechanism.** `notes.title_source` governs; the engine never
  writes a title. `note_title.suggest` discards a title that repeats a
  prompt example (`prompts.echoes_example`) or names something the
  transcript never says (`support.new_names`, a title word counting as
  said when a transcript word shares its first four letters — English
  titles are title-cased). On the ten synthetic recordings every model
  title passed. `stats.title_hash` never existed in this repository.
- **One noise policy.** ADR-0059's "a flagged line above half the window's
  words is not noise" is a `verify.confirm_noise` rule; such a flag is
  advisory.
- **Order in the job:** classify → name → extract; neither of the first
  two can stop the document.
- **Prompt version** `2026-10-12`; the title prompt is part of the pinned
  fingerprint.
- **Migrations** 0057 (titles), 0058 (recording types), 0059 (generated
  lines), 0060 (weekly report reader). They were never numbered otherwise
  here, so nothing was renamed.

## Consequences

- A title is sometimes left as the placeholder where a looser rule would
  have named the note; that is the cost of never inventing a name.
- Production entity correction is glossary- and roster-only until the
  staging numbers clear 0.9.
- The closure gates are proven on synthetic data only. A pass or fail on
  `eval/notes/v2` supersedes the synthetic column; the ADR does not change
  unless a rule above flips.

## Trigger conditions for revisiting

- `judge_unsupported_rate − unsupported_rate ≥ 0.02` on `eval/notes/v2`, or
  `not_said` dismissals > 5 % of written lines in the weekly report.
- `model_tier_precision ≥ 0.9` on `eval/notes/v2` (turn the tier on in
  production) or < 0.5 in staging data (turn it off there too).
- Kept-line rate < 50 % or regenerate rate > 40 % after four pilot weeks.
