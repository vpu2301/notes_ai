# ADR-0054: The legacy batch clusterer is kept (removal precondition not met)

Date: 2026-09-19
Status: Accepted — revisit when the precondition holds
Sprint: 32 (B-4)
Supersedes: nothing yet (the batch half of ADR-0045 stays in force)

## Context

Sprint 32 planned to delete the legacy batch clusterer
(`OfflineClusteringConfig`, `cluster_embeddings*`, `_average_linkage`,
`_merge_close_centroids`, `_sample_indices`, `LegacyEcapaDiarizer`,
`MDX_DIAR_ENGINE=legacy`) once engine v2 (pyannote community-1, ADR-0052)
had proven itself. The precondition, set at planning: v2 the default for
≥ 14 days, production correction rate ≤ 10 %, no rollback to `legacy` in
that window.

## Decision

**Not removed.** None of the three conditions holds on 2026-09-19:

- v2 has never been the default — it has never run: the gated model was
  not fetched (no HF token with the accepted terms; ADR-0052 is Proposed).
- There is no production correction rate: the weekly report
  (`make weekly-speakers`) returns 0 rows — no diarized job has been opened
  since `result_first_read_at` exists.
- Legacy is the only engine that has run, so "no rollback" is vacuous.

An unmet quality bar is the reason not to delete the fallback; sunk cost is
not a reason to keep it either — when the precondition holds, delete it as
planned (frozen copy for the eval baseline under
`scripts/eval/engines/legacy_frozen.py`, `sim_cluster_overcount.py` pointed
at it, the `ecapa-fetch` stage dropped from the asr-worker Dockerfile, the
asr-worker mention removed from the ECAPA row in PINS.md). The streaming
modules dictation-service imports (`clustering.py`, `embedder.py`,
`vad.py`, `chunking.py`, `attribution.py`) stay regardless.

## Consequences

- Legacy stays the default engine and the rollback target; it is also the
  engine all Sprint 28–31 measurements were taken with (with the roster
  guard it meets the §6 count targets on the test split: 88 % exact,
  93 % on 1–4 speakers, 4/4 two-speaker — see ADR-0052).
- Two engines keep being maintained behind the seam; `MDX_DIAR_SHADOW_ENGINE`
  is the tool to build the 14-day evidence once v2 can load.
