# Sprint P1 — Prompt engineering and model comparison in Settings

## Goal

An authorized workspace admin can edit instructions, choose stage models and supported parameters, run fixed-input comparisons, inspect evidence and activate a demonstrably better configuration. Dependency: F1/F2. Extend the implemented page and APIs rather than rebuild them. Owner: frontend + backend + product reviewer.

## Existing foundation

- web/src/pages/settings/AINotesSettingsPage.tsx
- web/src/pages/settings/aiNotes/{EditorPanel,TestPanel,ComparePanel,shared}.tsx / .ts as appropriate; inspect actual filenames.
- domain/{prompt_profiles,prompt_profile_repository,experiments}.py
- routers/{ai_profiles,ai_experiments}.py, jobs/evaluate_note.py
- meeting_doc/{prompts,stage_provider}.py, existing prompt_templates/.

The current editable stages are extraction, composition, verification. Common, context and deduplication instructions are bundled resources. Preserve this distinction in the UI and prompt documentation.

## P1-01 [P0] — Make editor behavior match execution

Keep the existing stage editor. Provide helpful stage labels: Extract facts; Write notes; Verify meaning. Paste/save uses the instruction blocks in 04-settings-prompt-pack.md. Save creates an immutable version; it never implicitly activates it. Display active versus draft version and a diff.

Validate required variables (output_language, length_mode), allowed stages, length/context limits and compatible schema version server-side. Blank text must have explicit semantics: use bundled instructions, not an accidental silent override. Preserve the composition parser's named subsections. Invalid section/variable edits produce actionable validation errors.

The current effective_instructions preview assumes the multilingual path for extraction. Replace approximate preview with a shared resolver taking the exact effective flags, language, model capability and profile snapshot. The same resolver must feed preview, experiment and production jobs. Expose each composition subcall's effective prompt (summary, topic bullets, heading) in an advanced preview rather than only a summary prompt presented as the whole stage.

Show code-owned common/context/dedup rules read-only in advanced settings. Workspace admins edit task wording, not provenance contracts, source access controls or semantic-validation bypasses. If future editing of those bundled stages is needed, add it explicitly with version/schema tests; do not imply existing three-field Settings already controls them.

Acceptance: a saved profile's resolved prompt hash equals the actual request hash for the same inputs and mode; no hidden legacy rule still labels another language as noise; disabled fidelity is clearly visible and cannot masquerade as verified output.

## P1-02 [P1] — Models and settings that actually apply

Reuse model capability registry and existing processor acknowledgement/plan/budget gates. Extraction, composition and verification have explicit bindings. Show actual model used, not just requested model. Disable unsupported temperature/reasoning/seed controls; never silently ignore a setting. Do not expose arbitrary endpoints or secrets.

Show supported token limits and timeout controls. Record settings and actual auxiliary calls in the run snapshot. Provider fallback is visible and prevents interpreting the result as a clean comparison of the originally selected models. Changing settings affects future jobs only; replays intentionally create new snapshots.

Acceptance: selecting a stage model changes that stage's actual requests; unsupported parameters fail validation; displayed fallback and usage agree with worker records.

## P1-03 [P0] — Practical prompt experimentation workflow

Flow: Duplicate active profile → edit one stage → save candidate → select existing note/test set → compare baseline/candidate → review findings → activate or revise.

Use the same immutable transcript snapshot, output language and length for both candidates. Do not rerun ASR. Default to three repetitions, with visible request count and estimated cost before starting. Allow a quick single-run preview but label it insufficient for release evaluation. Never rewrite source notes, action items or glossary during experiments.

Default comparison changes prompts with model held fixed. Then compare models with prompt held fixed. Allow combined changes but label them as multiple variables. Support cancellation and partial failure; preserve failed runs in the report. Use existing idempotency/budget controls and validate their behavior rather than implementing duplicate infrastructure.

Comparison view shows final notes, original-language evidence, source revision, effective profile/hash, actual model, final-check results, omissions, repeats, latency and estimated cost. Without gold annotations, completeness is “not measured”, not an invented percentage. LLM judge assessments are advisory and labeled; human factual review is separate from preference.

Provide blind A/B review with A/B/Tie/Neither and factual error labels. Randomize presentation order per pair. A user should be able to identify a prettier but factually wrong output.

## P1-04 [P0] — Activation and regression protection

Use atomic active-version updates with expected revision and existing permissions. Confirm activation affects future generations only. Require passing critical replay cases for the candidate's compatible code/schema/profile version before production activation. Keep a candidate as draft if evidence is missing. Rollback selects a prior compatible version, without changing existing notes or queued jobs.

Do not auto-promote a winner by preference or cost alone. Show precision/recall, critical errors and cost separately. Where a candidate improves readability but fails inversion/participant/coverage tests, keep it unapproved. Re-run relevant tests when bundled instructions or final verification logic changes even if workspace text is unchanged.

## End-to-end tests and definition of done

- [ ] Save/edit/version history works without changing active production behavior.
- [ ] Three instruction fields affect the corresponding actual model requests.
- [ ] Preview uses exact flags and stage-specific prompts, not a simplified approximation.
- [ ] A/B runs share source revision and never mutate source notes or glossary.
- [ ] Model support, permission, processor, budget and fallback states are correct.
- [ ] Blind review, source navigation, failure/cancel and stale activation conflict work.
- [ ] A correct baseline and inverted candidate are distinguished in final accuracy results.
- [ ] Activation and rollback preserve immutable history and pinned jobs.
- [ ] Keyboard access, readable comparison layout and existing localization are preserved.

Deferred: automated prompt search, fine-tuning, arbitrary providers, public leaderboards and automatic winner promotion. The first useful product is a reliable edit/test/compare/activate loop.
