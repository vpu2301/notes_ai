# ADR-0067 — The ASR engine is chosen by a pre-registered rule

**Status:** Proposed. The rule is registered and no arm has been measured. · **Date:** 2026-10-01 ·
**Implements:** Sprint TQ4 (transcript-summary-quality track) · **Evidence:** `02-market-analysis-local-asr.md`,
`docs/eval/asr-bakeoff-2026-11.md`

## Context

Today the transcript is decoded by whisper-large-v3-turbo. On the EU GPU path it runs as CT2 fp16 on
an HF T4 (`hf_eu_asr`). On the dev Mac it runs on whisper.cpp (`dev_mac_asr`). The in-process CPU
worker runs large-v3 int8. Public numbers are read speech: Whisper-v3 FLEURS en 4.25 / de 4.30 /
uk 6.51 and Parakeet-TDT-0.6B-v3 en 4.85 / de 5.04 / uk 6.79. They are not meeting audio. The r04
audit found that the dominant transcript failures are non-speech hallucination (architectural in
Whisper) and entity drift (TQ3). This ADR fixes how the engine is chosen **before** any arm is
measured. The rule below is the canonical text from `sprint-TQ4-engine-bakeoff-parakeet.md`, copied
verbatim. The engine is decided by its numbers, not by this document.

## Pre-registered decision rule (verbatim)

Arms, all through the production worker path with TQ2 guards on and TQ3 unification on where shipped
(the report states `entity_view: unified | raw` and the same view is used for every arm):

- **A** `hf_eu_asr` — whisper-large-v3-turbo (today).
- **B** `cand_whisper_v3_asr` — whisper-large-v3 (full), same Speaches image, `WHISPER__MODEL=Systran/faster-whisper-large-v3`, fp16 T4.
- **C** `cand_parakeet_asr` — `nvidia/parakeet-tdt-0.6b-v3` in `deploy/asr-server`, T4.
- Mac: `dev_mac_asr` (turbo, whisper.cpp) vs `dev_mac_parakeet_asr` (parakeet.cpp `--timestamps`, Metal; FluidAudio CoreML CLI as a second measurement for C5).

Measured on `eval/asr/v1` **test split**, per language, guards on, unifier on:

| Criterion | Adopt C (Parakeet) if… | Otherwise |
|---|---|---|
| TR-01 WER | C ≤ min(A, B) + 1.0 pp absolute on **each** of de, uk, en, and C's uk ≤ A's uk | keep Whisper family |
| TR-04 entity error rate (same entity view for all arms) | C ≤ min(A, B) + 2 pp | — |
| TR-02 hallucination | C's `halluc_chars_per_nonspeech_min` ≤ 25 % of A's (guards on) and `artefact_hits` = 0 | — |
| TR-06 code-switch coverage | C ≥ 0.85 (per-run language ID is done by our chunker, not by the model) | — |
| TR-08 timestamps | C median MAE ≤ 120 ms, missing = 0 | — |
| TR-12 speed | C rtf ≤ 0.10 on T4 and ≤ 0.05 on an M-series Mac | — |
| Cost | C cost per audio hour ≤ A's | — |

If C fails only on TR-01 uk by ≤ 1.5 pp but wins TR-02 by ≥ 75 % and TR-12 by ≥ 5×: **run the shadow anyway** and let the correction-rate telemetry decide (kept-line rate, transcript edit rate per language) — record this as a pre-registered exception.

Within the Whisper family: adopt **B** over **A** if B's uk WER is ≥ 2 pp better and rtf stays ≤ 0.25; else keep A.

Any outcome is written to ADR-0067 with the tables. No engine ships on a demo.

## How the rule is applied (mechanics, not a change to the rule)

- **Measurement.** `make eval-asr BACKEND=<arm> SPLIT=test GUARDS=on` runs `eval/asr/v1`. Speed comes
  from three runs per arm. "Unifier on" means the eval scores the TQ3 applied view
  (`asr_eval.unified_view`), the same for every arm, so `entity_view: unified`.
- **Language groups.** A language with n < 3 is **not measured** (quality criteria §6 rule 4). A
  criterion that needs it cannot pass, so C cannot be adopted on that language's absence.
- **Shadow** (adopted arm, two weeks, ≥ 200 jobs): `MDX_ASR_SHADOW_BACKEND`, `MDX_ASR_SHADOW_RATE`
  (0.2) and `MDX_ASR_SHADOW_BUDGET_HOURS`. The worker stores only numeric diffs in `diagnostics.shadow`.
- **Switch.** A routing PR (`asr: {standard: <winner>}`). The loser stays as `cand_*`. Rollback is a
  revert of that PR, and the old endpoint stays deployed for one release.

## Outcome

_Not yet measured._ `eval/asr/v1` holds no labelled recording (TQ1 T2 is open), and neither HF
endpoint has been raised. The tables go here, unchanged in form, when the test split exists.

What exists (2026-10-01, `docs/eval/asr-bakeoff-2026-11.md`) is synthetic and has no standing
under the rule:

- The three arms are equal within noise on five TTS files.
- Sent straight to the engine, turbo writes "Untertitelung des ZDF" over noise and "Vielen Dank."
  over silence, and Parakeet writes nothing.
- FluidAudio's CoreML Parakeet v3 runs at 0.6–1.5 % of real time on the dev Mac.

## Revisit triggers

Any of these reopens the decision:

- a nightly TR gate regression;
- a uk transcript edit rate ≥ 2× de for six weeks;
- a permissively licensed model with published uk FLEURS ≤ 6.0 **and** non-speech ≤ 5 chars/min;
- a Parakeet/Nemotron successor with offline de/uk numbers and word timestamps;
- a licence change on a shipped model;
- Voxtral or Apple adding Ukrainian (that reopens options D and C5 of the market analysis).
