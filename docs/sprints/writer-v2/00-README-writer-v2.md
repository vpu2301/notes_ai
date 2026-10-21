# Writer v2 — the model writes the note

This folder replaces the `engine-parity` pack for everything about how a note is written. What stays from the old pack: `sprint-B3-transcript-code-switching.md` (the words), `task-2-scorer-calibration-gold-trace.md` (measuring), `03-corpus-plan.md` and `04-public-corpora-what-and-how.md` (what we measure on), the hand tables and reference comparisons (`eval-*.md`), and `01-instruction-structures-to-paste.md` (the texts that become templates). Everything else in that pack is history.

| Order | File | What | Length |
|---|---|---|---|
| 0 | `00-concept-writer-v2.md` | How it works — read first | — |
| 1 | `sprint-R0-remove-the-old-path.md` | Delete the extraction/composition/gate pipeline, the template matcher, the classifier, the fallbacks, their prompts, tests and eval scorers. Lands together with P1 on one branch. | 2 days |
| 2 | `sprint-P1-the-writer.md` | The new pipeline: prompt + template + instruction text → model → Markdown → stored → parsed into the items the clients already read. Long recordings in windows, merged by the model. | 3 days |
| 3 | `sprint-P2-templates-and-instructions.md` | Templates as editable text; the workspace instruction text (N-series) and the Settings page wired to the writer; per-note template choice; model settings that still apply. | 3 days |
| 4 | `sprint-P3-evidence-clients-and-scoring.md` | Timestamps → evidence popovers, PDF and shared page on the new items; the optional "unverified" marker as a second model call (off by default); the scoring loop: six recordings × 3 runs, hand-scored against the references; prompt/template iteration. | 1 week |

Rules that stay from the repo: tenant context on every job, content never in logs, `PROMPT_VERSION` + fingerprint, OpenAPI dump, lint + tests, no AI attribution in commits, public broadcast material only as fixtures, nothing real under `eval/`.

Rules new to this pack: **code never writes, deletes, reorders or rewrites a line of a note.** No gate, no fallback prose, no threshold inside the pipeline. If a note is wrong, the prompt, the template or the model changes. Quality is measured after the fact, by people and by the eval, never enforced by code in the path.

How to run with Claude Code: copy this folder to `docs/sprints/writer-v2/`; paste "Read docs/sprints/writer-v2/00-README-writer-v2.md, 00-concept-writer-v2.md and <sprint file>. Do Inspect first; stop if a listed fact is false. Do the tasks in order, verify after each. Do not add any check, gate or fallback that changes the note's text; if you think one is needed, stop and ask. Finish with Report back. Do not commit."
