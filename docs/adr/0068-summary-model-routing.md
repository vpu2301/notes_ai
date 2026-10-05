# ADR-0068 — The summary model staging routes is chosen by a written rule

**Status:** Proposed. The rule is registered; the measurement it names does not exist (see Outcome). ·
**Date:** 2026-10-01 · **Implements:** Sprint SQ1 T5 (transcript-summary-quality track) ·
**Related:** ADR-0046 (hosting is configuration), ADR-0067 (the ASR engine rule), engine-v2 decision 3
("a config PR plus an eval report")

## Context

Staging and prod route every chat operation to `hf_eu` (Gemma 3 4B on an HF endpoint). Dev
routes the writing to `mistral_eu` (Mistral Large 3, `mistral-large-2512`) and the short
operations to `mistral_eu_small` (Sprint L2). Before SQ1, neither Mistral model had an eval report,
and every notes number came from 11 synthetic fixtures. Nobody had chosen the model that ships;
it had been left as the earliest configuration.

## Rule (written before any SQ1 run; verbatim from the sprint)

> Staging routes the **cheapest** arm that passes every pilot gate in §3 on the test split per
> language; if none passes, the arm with the highest `key_fact_recall` whose `unsupported ≤ 1` and
> `wrong name/number/date = 0`, and SQ2 starts on it. A vendor is routable in staging only when
> `docs/legal/third-party-notices.md` lists it (Mistral: done) **and** `docs/deploy/inventory.md`
> carries its secrets, endpoint and cost row (Mistral: missing — add it in this task). Record the
> choice, the table and the revisit trigger (any nightly gate regression; a cheaper arm passing).

The arms are `hf_eu` (Gemma 3 4B, what staging ships), `mistral_eu` (what dev ships), `dev_mac`
(local) and `single_pass` on `mistral_eu` (the baseline to beat). Each runs on `eval/notes/v2`
against the ASR snapshot and the human-corrected transcript. §3 means `01-quality-criteria.md` §3.

**Enforcement.** `scripts/ci/check-routing-has-report.py` (`make check-routing-report`, in CI)
fails when `routing` (or a staging/prod `env_overrides` entry) names a chat backend that has no
`eval/notes/v2` report at the current `PROMPT_VERSION`. A recorded, expiring waiver in
`docs/eval/routing-waivers.yaml` is the only alternative to a report.

## Owner decision that changes the inputs (2026-10-01)

The owner will not label a gold set for now. Notes are judged by running real recordings and
reading them side by side. So `eval/notes/v2` stays empty, and the rule's measurement cannot
be taken as written. This ADR keeps the rule, rather than quietly replacing it with an
impression, and records what follows from it:

1. **Staging stays on `hf_eu`.** That is the status quo, not a choice made by the rule. It is
   held under a waiver that expires 2026-12-31 (`docs/eval/routing-waivers.yaml`).
2. **Switching staging to Mistral needs one of two things**, together with the processor
   prerequisites below:
   - an `eval/notes/v2` report and the rule applied; or
   - an amendment to this ADR that replaces the rule. The amendment names what the owner's
     side-by-side review is, how many recordings it covered, and the revisit trigger. It also
     needs a new waiver for `mistral_eu` at the current `PROMPT_VERSION`.
3. **Processor prerequisites for Mistral:**
   - the third-party notice (done);
   - the inventory row with secrets, endpoint and cost (added in SQ1);
   - `api.mistral.ai:443` in `scripts/k8s/egress-allowlist.sh` (**open**, added with the routing PR);
   - the per-environment `MISTRAL_API_KEY` in `mdx-model-keys` (**open**).

## Outcome

There is no rule result. What exists is synthetic and has no standing under the rule:
`docs/eval/notes-v2-baseline-2026-10.md` holds the m01–m11 numbers for `mistral_eu` (pipeline
and single-pass) and the attribution of the Q6 → now recall drop on `dev_mac`.

## Revisit triggers

Any of these reopens the decision:

- a nightly gate regression;
- a cheaper arm passing;
- `eval/notes/v2` gaining labelled recordings;
- the waiver's expiry (2026-12-31);
- the owner's review favouring an arm. That needs the amendment described above.
