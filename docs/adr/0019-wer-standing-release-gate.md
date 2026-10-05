# ADR-0019 — WER eval is a standing release gate

- Status: accepted; harness implemented 2026-09-30 (Sprint TQ1), gate armed when the first baseline report is committed
- Date: 2026-05-12
- Sprint: 07
- Deciders: ML/MLOps lead, NLP lead, product lead

## Context

Up to sprint-06 we shipped Whisper/Prompts/NLP changes without an
automated, cross-sprint quality metric. Every sprint's tests pass on
unit corpora, but cross-sprint regressions (a number-norm change that
worsens overall WER, a prompts tweak that degrades cardiology
specifically) are easy to miss until someone notices in production.

## Decision

Stand up a nightly WER + RTF + number-norm eval that runs against a
versioned reference corpus (`eval/corpus/v1`) on the same GPU class
the demo uses, persists results to `audit.eval_runs` /
`audit.eval_utterances`, and compares the latest run to a rolling
baseline in `audit.eval_baseline`.

Regression thresholds (sprint-07 calibrated):

- Per-language WER may not increase by more than **1.0 pp absolute**.
- RTF p95 may not drop by more than **0.05**.
- Number-norm accuracy may not fall below **95%** on any category.

A regression alerts `#eval-regressions` Slack with the
nightly-wer GitHub Actions run link. The ML/MLOps lead triages
within one business day. Re-baselining is permitted **only** when a
new model version, NLP pipeline version, or corpus version ships
(documented in an ADR).

The corpus is part of the repo (LFS-backed). PII sweep
(`scripts/eval/check_corpus_pii.py`) runs on every PR.

## Consequences

Positive:
- Quality changes are now measurable, not anecdotal.
- Per-specialty breakdown catches regressions invisible at the
  aggregate level.
- Determinism contract (model + prompts + pipeline_version hashed
  into every run) lets us bisect.

Negative:
- Nightly GPU runner is a non-zero cost (~30 min/day on A10G).
- Corpus authorship is expensive — clinical content lead + linguist
  consultant. Funded for v1; v2 expansion is sprint-08+.

## Out of scope

- Latency under load (sprint-08 will add a load-test harness).
- Adversarial / accent eval — v2 corpus.

## Links

- `scripts/eval/run_wer.py`.
- `scripts/eval/compare_to_baseline.py`.
- `.github/workflows/nightly-wer.yml`.
- `docs/eval/wer-methodology.md`.
- Sprint-07 spec §4 (eval pipeline) + §5 (baseline + alerts).

## Amendment (2026-09-30, Sprint TQ1) — built at last, on real recordings

Nothing above was built. No WER code existed in the repo until TQ1: the
scripts, tables and workflow in **Links** were never written, and
`eval/corpus/v1` never existed. The only gold set was speakers-only
(`eval/speakers/v1`, RTTM, English). This amendment records the gate as
built and supersedes the parts of the decision that it changes.

**What is built.**

- **Corpus:** `eval/asr/v1` holds real, consented recordings (de ≥ 5,
  uk ≥ 4, en ≥ 3, code-switched ≥ 2, the r03/r04 regression podcasts).
  Only the manifest is in git. References, spans, RTTM, alignment and
  audio live in the private eval bucket
  (`s3://notes-eval/asr/v1/<id>/`). This **supersedes** "the corpus is part
  of the repo (LFS-backed)": a human-corrected transcript is personal data.
  `scripts/ci/check-no-eval-audio.sh` fails on tracked content under
  `eval/asr/**` and `eval/notes/**`. Labelling rules are in
  `docs/eval/asr-labelling.md`, which adopts verbatim-lite.
- **Harness:** `scripts/eval/asr_eval.py` runs a `config/models.yaml`
  backend through `asr_worker.processor.decode_recording`, the function a
  job calls, so every guard is measured as shipped. The metrics are in
  `scripts/eval/asr_scoring.py`. They cover WER on speech regions after
  per-language normalisation, entity and number/date error, entity
  consistency, hallucinated characters per non-speech minute, artefact
  hits, coverage and unexplained gaps, code-switch coverage and translated
  segments, non-speech marking, word-timestamp error and RTF. Each maps to
  a taxonomy code (`scripts/eval/taxonomy.py`). The report is
  `docs/eval/asr-<date>-<backend>-<split>.{json,md}`, with numbers and ids
  only, `n` per language, "directional" below 20 and "not measured"
  below 3.
- **Gate:** `.github/workflows/nightly-asr.yml` runs the self-hosted
  `mdx-eval` runner nightly. `scripts/eval/compare_asr.py` compares each
  backend against its committed baseline,
  `docs/eval/asr-baseline-<backend>-test.json`. Per language (de, uk, en)
  and overall, the gate is:
  - WER may not rise by more than **1.0 pp absolute**. This rule is unchanged.
  - TR-02 (`halluc_chars_per_nonspeech_min`, `artefact_hits`) and TR-03
    (`speech_coverage`, `unexplained_gaps`) may not worsen. This is new.
  - A comparison across backends, splits or corpus versions is refused,
    never passed.
- **Regression checklists:** `make eval-asr-assert` runs the r03/r04
  transcript checks. A check a later sprint owns is `XFAIL` with that
  sprint's name.

**What changes from the original decision.**

- Results are committed reports, not `audit.eval_*` tables. An eval run
  is not an audit event, and the reports are reviewable in a PR.
- The RTF gate moves to TR-12 (p95 ≤ 0.25 on the staging shape). TQ2 and
  TQ4 own it. The nightly reports RTF but does not gate on it, because a
  scale-to-zero endpoint's cold start would make the gate flap.
- Number normalisation is measured as `number_date_error_rate` on gold
  number/date spans (TR-04), not as a separate category accuracy.
- Alerting is the failed workflow run. No Slack integration exists.
- Re-baselining is allowed, as before, only when a model, backend, guard
  or corpus version changes. It is done in a PR carrying the new report
  and a line in `docs/product/asr-decisions.md`.

**Links (current).** `scripts/eval/asr_eval.py`, `asr_scoring.py`,
`asr_gold.py`, `compare_asr.py`; `eval/asr/v1/README.md`;
`docs/eval/asr-labelling.md`; `.github/workflows/nightly-asr.yml`;
`docs/sprints/transcript-summary-quality/sprint-TQ1-asr-truth-and-wer-gate.md`.
