# What Settings › AI notes edits, and what it does not

Settings › AI notes edits **three task texts**. Everything else a run sends is owned by
the service, versioned with it, and shown read-only.

| Shown as | Profile stage | Calls it reaches | Bundled text |
|---|---|---|---|
| Extract facts | `extraction` | `extraction` | `prompt_templates/extraction.md` |
| Write notes | `composition` | `composition.summary`, `composition.topic` (small model: `composition.bullets`, `composition.heading`) | `prompt_templates/composition.md` |
| Verify meaning | `verification` | `verification.meaning`, `verification.final` (the F1 final check) | `prompt_templates/verification.md` |

Code-owned, not editable in Settings: `common.md` (in every call), `context.md`
(`context`), `deduplication.md` (`deduplication`), the participant check
(`participants`), every output contract, the data guard and the builders' own rules.
Making any of them editable is a separate change with its own version and schema
tests; the three fields do not control them.

## Rules a stage text must keep

- **Blank means bundled.** An emptied field is saved as `null`: the bundled text is
  used. An empty override is refused (`empty`).
- **Placeholders.** Only `{{output_language}}` and `{{length_mode}}` exist. A stage
  must keep every placeholder its bundled text uses (`missing_variable`): Write notes
  keeps `{{output_language}}`.
- **Write notes sections.** The composition text keeps `GENERAL`, `SUMMARY SUBTASK`,
  `TOPIC/BULLET SUBTASK`, `HEADING SUBTASK` and `CHRONOLOGY`, each once, each on its own
  line (`missing_section`, `duplicate_section`, `unknown_section`). Each composition
  call gets `GENERAL` plus its own section.

## One resolver

`domain/prompt_profiles.resolve()` produces every call's exact system text from the
profile, the flags (multilingual evidence, fidelity), the output language, the
extraction model's small-model profile and the bullet budget. The preview, the
experiment snapshot and the production snapshot all use it; each run records the sha256
of every system text it sent (`stats.calls[].system_hashes`) next to the resolver's
(`stats.prompt_hashes`), and Run details marks which resolved calls were sent. A retry
adds a suffix and is a different text.

With multilingual evidence off, no profile text is sent: the preview for *New notes
here* marks edited stages `not_applied`, and the page says the previous engine runs.
Test runs always take the multilingual + fidelity path, so a test can differ from a
regenerated note until the flags are on.

## Activation

A version that never wrote this workspace's notes needs an evaluation (an experiment
with no critical review finding) **and** a pass of the critical cases on the current
service version (`suite: "critical"`; `domain/acceptance_cases/`). A change to the
bundled texts, prompt schemas, algorithm or final check invalidates earlier passes.
A rollback to a previously active version needs neither.
