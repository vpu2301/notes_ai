# Implementation status

State on branch `notes-generation-improvements` after 51b4e7b, uncommitted at the time of
writing. Versions: prompt `2026-10-18.5`, algorithm `2026-10-18.final-check`, final check
`2026-10-18.final-check`. Every measured figure below names its denominator; release
targets (README) are targets, not results.

## F1 — runtime and final-output fidelity

Implemented:

- **Provenance per run** (F1-01): `stats.runtime` — worker build SHA (`MDX_BUILD_SHA`,
  Dockerfile `ARG BUILD_SHA`), the API build that pinned the job, flags as executed and
  their source (`snapshot` | `deployment`), flags the worker's deployment sets
  differently (`flags_differ`), registry fallbacks; `stats.calls` = the backend and model
  that answered each stage. `GenerationView.provenance`; web "Run details".
  `GET /v1/ai/runtime`; Settings › AI notes no longer claims multilingual evidence or
  checks when the flags are off. Experiment snapshots are labelled `run_kind: experiment`.
- **Final check** (F1-02): `meeting_doc/final_check.py`, `pipeline.finalize()` after
  `doclint.enforce`, before `writer.apply` (worker and experiments). Every asserted line
  (not headings, framing, presenters, quotes, figure rows; not a line equal to a cited
  fact's verified text) against the cited facts' original transcript lines with the
  verification binding (metered apart as `final_check`, the same model). One repair,
  re-checked; else a one-fact line falls back to its fact, any other is held for review
  (`final_unverified` rows) and the note is incomplete. Reserved budget (≤16 calls,
  batches of 8, 90 s timeout); cache by text + evidence + verifier/prompt/system hash.
- **Polarity routing and telemetry** (F1-03): comparison/approval words route claims to
  the meaning check; golden claims g9–g15 (both directions), sentinel ml11;
  `make eval-final-check` (corrupting composer on a real model); `stats.final_check`
  (ids and counts only).

Measured (mistral-large-2512, 3 runs):

- Corrupting composer: 56 of 63 corrupted lines corrected or restored, 9/9 faithful
  lines kept; the 7 that passed are the verifier's known gaps (could→will 3,
  hypothetical→done 1, host's view given to its subject 3).
- Golden claims (meaning check): precision 0.87 (55 corrupt rejected of 63), recall 0.98
  (53/54); same three gaps.
- Unit test: without the final check a composed "besser" on verified "schlechter" passed
  the word gate; with it, restored.

Rollback: `MDX_NOTE_FIDELITY=false` (removes the final check with the rest of fidelity) or
a code revert. Jobs keep their pinned snapshot: a job pinned with algorithm
`2026-10-18.fidelity` runs without the final check. Readers tolerate absent `runtime`,
`final_check`, `prompt_hashes`.

## F2 — participants, glossary, coverage

Implemented:

- **Participants** (F2-01): an introduction cue must stand right before a person-shaped
  name (`verify.intro_cue`, `person_shaped`); weak cues ("das ist", "this is") and
  single words are `pending` until the participant check (`_confirm_participants`, one
  call, ≤8 items; entity type and participation apart) accepts them; a voice is linked
  only by the check's line or an immediate same-language handover; a minor
  other-language voice in a broadcast is a quoted clip; framing naming an unaccepted
  participant is not used. Root cause of the "Midterm-Wahlen" guest: a cue anywhere in
  the host's turn, then the next voice (the inserted English clip).
- **Glossary** (F2-02): `entities.change_kind` — article, grammatical ending and
  capitalisation are not corrections (also for glossary entries saved earlier); server
  guard on `POST /v1/glossary` (`ignored_heard_as`); `suspect: grammar_variant` on
  entries; read-time filter of stored rows; a correction is typed `person` only with
  entity evidence. "Names in this note" (web `CorrectionsPanel`, macOS, iOS) shows
  "In the glossary" only from the server's answer or an existing entry; Remove offered
  where the user may delete. Dev-database provenance: the nine entries written
  2026-10-18 10:10:59–10:11:16 match nine "accept" clicks; none were written
  automatically. No entry was changed or removed.
- **Coverage** (F2-03): per-fact `stats.fates` (evidence position, meaning outcome or why
  undecided — budget/unavailable/malformed apart from contradicted — merge target,
  placement); bounded recovery pass for high-risk lines with no writable fact (lines
  only: nothing is targeted where nothing was said); German nouns and foreign-language
  evidence no longer block composition when the final check reads every line; central
  claims kept in a full topic; a call to action is not the overview.

Measured (3 runs, before P1 changes):

| Case | F1 | F2 |
|---|---|---|
| ml01 conditional payment | 7, 7, 7 /10 | 7, 10, 10 /10 |
| ml11 polarity | 13, 14, 14 /15 | 14, 15, 14 /15 |
| ml12 participants (current code) | — | 9, 9, 9 /9 |
| m06 / m09 / m10 / m11 | 13/23, 9/9, 10/10, 10/11 | 16/23, 9/9, 9/10, 11/11 |

Real-note replay (reconstructed transcript, synthetic timings): the promise is extracted,
supported by meaning against the English line, written in the overview with both
conditions; it appeared twice (two paraphrases of one passage, too few shared words to be offered to the duplicate check). Fixed after that run: facts restating the same passage go to the meaning-based duplicate check whatever their word overlap (`merge.same_source`); the code's veto on amounts, negation and conditions still applies.

Rollback: the participant check, recovery pass and gate relaxations run only with
fidelity (and the final check): `MDX_NOTE_FIDELITY=false`. The grammar guard is code
(revert). Stored glossary entries are never modified by these changes.

## P1 — prompt engineering in Settings

Implemented:

- One resolver (`prompt_profiles.resolve`) for preview, experiment and production
  snapshots: every call's exact system text for the flags, language, small-model
  profile and bullet budget; each run records the sha256 of every system text it sent;
  a unit test asserts equality on a profile run. The run's summary headings moved from
  the system text into the data so the system text is resolvable.
- Validation: placeholders the bundled text uses (`missing_variable`), Write notes
  sections (`missing_section` / `duplicate_section` / `unknown_section`); blank = bundled.
- Editor ([what Settings edits](settings-editable-stages.md)): Extract facts / Write notes / Verify meaning; per-call preview for *New notes
  here* and *Test runs*, with sources (`profile`, `bundled`, `not_applied`, `code`) and
  hashes; code-owned rules read-only.
- Runs: requested vs answering model, fallbacks, `clean` comparison; estimated request
  count; one-run warning.
- Activation: a never-active version needs an evaluation and a pass of the critical
  cases (`suite: "critical"`: ml01, ml11, ml12 shipped in `domain/acceptance_cases/`) on
  the current `suite_version`; 409 `acceptance_required` otherwise.

Not done: browser end-to-end tests (Playwright) not run; no LLM judge exists (none is
claimed); the bundled Settings fields are unchanged — the prompt pack is a candidate
(`tests/fixtures/eval/profiles/bilingual_fidelity_candidate_v2.json`).

Rollback: activation of a previously active version needs no new evidence; profile
versions are immutable; snapshots and stats additions are read tolerantly.

## Prompt pack (04) — candidate evaluation

The three stage texts were evaluated as a profile against the bundled baseline: same
model (mistral-large-2512), German output, Detailed length, every flag on, 3 runs each,
code at prompt version 2026-10-18.5. Prompt-only change; nothing else differed.

| | Baseline (bundled) | Candidate v2 |
|---|---|---|
| Meaning check on golden claims: precision / recall | 0.89 (57/63 corrupt rejected) / 0.94 (51/54) | 0.81 (51/63) / 0.93 (50/54) |
| Corrupted claims accepted (critical) | 6: could→will ×3, host's view given to its subject ×3 | 12: adds entity swapped ×3, hypothetical→done ×3 |
| Corrupting composer: corrupted lines written as composed | 7 of 63 | 12 of 63 |
| Faithful composed lines kept | 9/9 | 9/9 |
| Critical-family check failures over 36 sentinel runs | 7 | 10 (ml01 lost the promise in 1 of 3 runs) |
| Critical cases ml01 / ml11 / ml12 | 3/3, 3/3, 3/3 | 2/3, 3/3, 3/3 |

Real note (PDF reconstruction, synthetic timings; German output, Detailed, 3 runs each,
code before the same-passage duplicate fix):

| Release target | Baseline (bundled) | Candidate v2 | Target |
|---|---|---|---|
| Critical failures (promise not in one line with its condition; not cited to the English line) | 6 in 3 runs | 5 in 3 runs | 0 |
| $5,000 promise written | 0 of 3 runs | 1 of 3 runs | every run |
| Final claims checked by meaning, supported or repaired | 88% (22/25) | 84% (16/19) | ≥95% |
| Weighted important-proposition recall (six election propositions) | 53% (19/36) | 42% (15/36) | ≥90% |
| Duplicate bullets | 0% (0/29) | 0% (0/22) | ≤5% |
| Runs marked incomplete | 3/3 | 3/3 | — |

No target but duplicates is met. At Detailed length with German forced the promise did
not reach the note in any baseline run, although the earlier replay (standard length,
language auto) wrote it: coverage on the real note is not yet reliable. Next diagnosis:
the per-fact `fates` of these runs (extraction vs merge vs selection).

Decision under the pack's own rule ("a result failing any critical case remains a
candidate"): **candidate v2 is not activated and is not made the bundled default.** Its
verification text is weaker than the bundled one on modality and entity identity. The
known gaps in both (could→will, a host's view attributed to its subject) remain open.

Code-owned rules from the pack are in the bundled defaults (prompt 2026-10-18.5):
`common.md` already held the common rule; `context.md` gained the context rule; the
entity prompt gained the entity rule (the server guard of F2-02 enforces it regardless).

## Shared test set — what exists and what is missing

- Real transcript: only a PDF reconstruction (`eval/notes/multilingual-real/r04_…`,
  labelled RECONSTRUCTED, timings synthetic, git-ignored), annotated with the six
  election propositions (weighted) and the faulty exported note as a negative example.
  It is the replay snapshot of record: the available exports (the note's PDF, which prints
  the transcript with speakers, and its Markdown export) carry no timings or per-turn
  languages, so timing-dependent checks are excluded and every result on it is labelled
  as on a reconstruction. Both exports are kept as negative examples
  (`r04_de_midterms_negative_example.json`, git-ignored).
- Synthetic counterexamples: ml01–ml12, golden claims g1–g15, three critical cases.
- Missing: at least six real recordings (DE/EN broadcasts, multilingual meetings, short
  quotes, monolingual controls) and two unseen ones for final review.
- `scripts/eval/notes_assert.py` prints the release-target summary with denominators:
  critical failures, final claims checked by meaning and supported, weighted
  proposition recall (annotated cases only), duplicate bullets, incomplete runs, time,
  tokens.
