# Sprint F1 — Runtime visibility and final-output fidelity

## Goal

Prevent a verified fact becoming an incorrect final note. Establish whether the intended new generation path actually ran. Dependency: current improvements branch; no new Settings features required. Owner: backend, with bilingual QA.

## F1-01 [P0] — Expose and verify the effective run configuration

Existing touch points: config.py, jobs/generate_note.py::run_configuration, domain/generation_service.py, profile snapshots, deployment values and generation diagnostics.

The reviewed production values and backend defaults disable MDX_NOTE_MULTILINGUAL_EVIDENCE and MDX_NOTE_FIDELITY; base Helm values enable them. A queued job uses its pinned snapshot. Do not assume changing environment variables or editing a profile changes a previously queued job.

Tasks:

- Show build SHA, effective prompt/profile version, both flags, output language, transcript revision, actual stage models and fallback reasons in generation details.
- Record whether flags came from a pinned snapshot or legacy deployment defaults. New replays must create new run IDs and snapshots; do not overwrite old evidence.
- Make the rollout decision explicit for the target environment. Enable the corrected path in the authorized test environment; activate production only after release gates. Do not leave the UI implying fidelity is enabled when its execution flag is off.
- Verify the API process and worker resolve the same intended configuration. Ensure preview/test/normal generation differ only when explicitly requested and labeled.

Acceptance: a reviewer can establish which code and prompts produced each compared result; changing settings cannot silently alter an in-flight job; fresh jobs reflect an authorized activation.

## F1-02 [P0] — Verify final assertions against original evidence

Existing pipeline.py::_confirm_meaning verifies extracted facts. _block_bullets, _summary and _Gate.reason can accept newly phrased output using lexical checks. Close this gap.

Add a final claim-validation boundary after composition, attribution patching and doclint.enforce repairs, before writer.apply persists generated prose. Cover overview, main bullets, child bullets, additional details and other asserted generated text. Resolve original transcript evidence via fact IDs; do not verify only against the model's previous paraphrase. Structural headings need topic/participant validation, not fabricated claim citations.

For each assertion check actor, recipient, quantity/unit, condition, negation, comparison direction and modality. Split compound assertions internally or require all material clauses to be supported. Existing exact quote and source-membership checks remain mandatory. The final checker is a separate stage invocation using the configured verification binding; do not claim a different invocation is an independent model unless it actually is.

Use bounded batches and a separate reserved final-check budget so extraction retries cannot exhaust all verification capacity. Cache verdicts only by final-text hash + evidence hash + verifier/config version. Any wording or evidence change invalidates the cache. One repair attempt is allowed, followed by validation of the repaired text. No subsequent semantic rewrite may bypass this boundary.

If verification fails or is inconclusive, preserve the candidate and source for review, exclude it from asserted prose, and display incomplete coverage. Do not publish a near-empty note as a successful high-quality result. Preserve existing human-authored text; the validator must not rewrite it automatically.

Acceptance tests:

| Case | Expected |
|---|---|
| Verified schlechter, composer produces besser | Final candidate rejected or corrected and rechecked |
| Correct extraction, summary loses both-chambers condition | Rejected; full condition restored or flagged for review |
| German summary of English evidence | Accepted when meaning matches despite low word overlap |
| Doclint introduces a changed claim | New wording validated before persistence |
| Final verifier times out or budget ends | Incomplete state; no unverified assertion published |
| Human-edited section | Preserved under existing writer rules |

## F1-03 [P1] — Add polarity sentinels and honest telemetry

Extend high-risk routing coverage for better/worse and equivalents, but do not use keyword lists as the sole correctness gate. Add paired cases besser/schlechter, mehr/weniger, supports/opposes, approved/not approved, and changed recipients. Verify both directions, not just the provided sentence.

Record final claims checked/supported/repaired/unverified, provider failures, budget failures, and source IDs. Keep transcript text out of ordinary logs. Tests must include a deliberately corrupting composer after a correct extractor. Existing ScriptedProvider tests verify control flow; add actual-model replay to measure real detection, without making deterministic assertions about external model wording.

## Definition of done and rollback

- [ ] Effective flags/model/profile provenance visible for the exact run.
- [ ] Final validation occurs after every generated rewrite and before all generated writes.
- [ ] Critical inversion and conditional-payment sentinels pass on three real-model runs.
- [ ] Failure paths preserve review evidence and report incomplete coverage.
- [ ] Added latency, cost and coverage change reported on the shared corpus.
- [ ] Revert via versioned configuration/code with compatible readers; do not rewrite existing notes or mutate pinned jobs.

Out of scope: replacing ASR, rebuilding model registries, adding new providers, automatic prompt optimization.
