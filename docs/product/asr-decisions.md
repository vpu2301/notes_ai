# ASR — decision log

One entry per decision the transcript track takes on measured numbers
(`docs/sprints/transcript-summary-quality/`). Numbers come from the committed
`docs/eval/asr-*.json` reports. Each entry names its report. A decision
without a report is not taken (taxonomy `P-MEAS`).

## Standing rules

| Rule | Source |
|---|---|
| **TQ4 pull-forward.** If the baseline WER on meeting audio with `hf_eu_asr` (turbo) exceeds 25 % for uk or 18 % for de, TQ4 (engine bake-off) runs before TQ3. TQ4 then gates entities on the raw transcript and says so. | Sprint TQ1 §"Decision this sprint produces" |
| **Re-baselining** of the nightly gate happens only in a PR. The PR carries the new report and a row here naming the model, backend, guard or corpus change that moved the numbers. | ADR-0019 amendment |
| **A language with n < 3 is not measured**, and a rule cannot fire on it. Below 20 the number is directional. | Quality criteria §6 rule 4 |

## Log

| Date | Decision | Evidence | Report |
|---|---|---|---|
| 2026-09-30 | Harness, gold format, CI content gate and nightly workflow built (TQ1 T1, T3, T5; T2 and T4 tooling). **The pull-forward rule has not been evaluated.** `eval/asr/v1` holds no labelled recording yet, so every language is "not measured". | `make eval-asr-validate` reports a composition shortfall | — |
