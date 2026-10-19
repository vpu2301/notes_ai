# Notes AI — corrective delivery plan

Prepared 2026-10-18. Base reviewed: notes-generation-improvements, commit 51b4e7b2d8b38c00a6a0704242829f9e7318bb6c in https://github.com/vpu2301/notes_ai.

These are development specifications, not applied changes. They replace the remaining delivery sequence of the earlier four-sprint plan: the branch already implements profiles, experiment APIs and an AI Notes settings page. Extend those implementations; do not rebuild them.

## Sequence

| Order | Sprint | Deliverable |
|---|---|---|
| 1 | [F1: runtime and final-output fidelity](sprint-F1-runtime-and-final-output-fidelity.md) | Know which path executed; prevent meaning changes after fact verification |
| 2 | [F2: participants, glossary and coverage](sprint-F2-participants-glossary-coverage.md) | Remove false guests/corrections and preserve important propositions |
| 3 | [P1: prompt engineering in Settings](sprint-P1-prompt-engineering-in-settings.md) | Edit stage instructions, change models/parameters, test, compare, activate and roll back |

One markdown file specifies each sprint. [04-settings-prompt-pack.md](04-settings-prompt-pack.md) supplies candidate instructions for the settings fields and code-owned rules. Sprint duration must be estimated by the team after task sizing; do not equate this scope with a guaranteed number of weeks.

Implementation state, measured results, provenance and rollback per sprint: [implementation-status.md](implementation-status.md).

## Evidence and limits

The supplied updated notes contain a reversed better/worse comparison, an event presented as a guest, article-removal suggestions presented as name corrections, and omission of the conditional $5,000 promise. Source inspection identifies paths permitting these errors; production stage artifacts were not available, so not every observed output has a proven runtime cause.

Do not modify ASR or acoustic speaker diarization in this work. The user verified their quality. Participant identity/role assignment and note composition remain in scope.

## Shared test set

Freeze the original bilingual transcript as a replay snapshot and include the supplied faulty output as a negative example. Obtain the real source JSON for exact timing/speaker metadata; a PDF-derived reconstruction must be labeled and must not claim measured timestamps. Add at least six recordings covering DE/EN broadcasts, multilingual meetings, short quotes, and monolingual controls. Keep two unseen recordings for final review. Include synthetic counterexamples separately.

Annotate critical propositions and original-language evidence, actors, conditions, amounts, polarity and relevance. In Detailed mode the election fixture must cover: election purpose/powers; seat/majority scenario; strategic Trump trade-off; conditional $5,000 promise with recipients; key campaign themes; host-attributed election-integrity discussion. These are source-fidelity requirements, not external political fact checks.

Run baseline/candidate three times on identical transcript revisions, length and output language. Review final displayed text, including overview, additional details and post-lint repairs. Report precision/recall with denominators, critical distortions, attribution errors, duplicates, excluded/unverified content, time, tokens, fallback and estimated cost. Do not average away a critical error or claim accuracy from word overlap. Proposed release targets: zero critical sentinel failures; >=95% supported final claims; >=90% weighted important-proposition recall in Detailed; <=5% duplicate bullets. These are acceptance targets, not current measured performance.

## Repository placement

Save this package under proposed docs/development/ai-notes-quality/stabilization/. Runtime defaults remain in the existing services/note-service/src/note_service/domain/meeting_doc/prompt_templates/; user-edited versions remain in existing profile persistence. Do not save tenant prompts into Git source at runtime.

Each sprint requires a reviewable PR, targeted tests, measured replay results, actual configuration provenance and rollback instructions. Production activation is explicit. Experiments must not write to live notes or trigger external actions.
