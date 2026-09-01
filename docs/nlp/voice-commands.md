# Voice Commands (dictation.v1)

The voice command FSM (pipeline Stage 1) detects intentional verbal
commands embedded in dictation. Every match has three gates:

1. **Pause-before**: silence ≥ `requires_pause_before_ms` between the
   previous content word and the command head.
2. **Confidence**: average word probability ≥ `min_avg_probability`.
3. **Edit-distance tolerance**: ≤ 1 substitution per phrase;
   substituted word's Levenshtein distance ≤ 2. Specs marked
   `exact_match_only` opt out of this tolerance entirely.

False positives cost trust more than false negatives — defaults err
toward "didn't fire". Frontend offers a 600-ms undo affordance and
emits `voice_command.undone` for telemetry.

Conversation-mode transcripts disable this stage entirely
(`stages_disabled: ["voice_commands"]`), so other meeting participants'
speech can never trigger editing operations.

## Catalogue

The catalogue ships as `infra/postgres/seed/voice_commands_<lang>.json`
(currently `uk` and `en`, 45 intents each). It covers:

- **Structure**: `newparagraph`, `newline`.
- **Punctuation** (one intent per mark): `period`, `comma`,
  `question_mark`, `exclamation_mark`, `dash`, `en_dash`, `hyphen`,
  `colon`, `semicolon`, `ellipsis`, paired quotes
  (`open/close_double_quote`, `open/close_single_quote`,
  `begin_quote`/`end_quote`), paired brackets
  (`open/close_paren`, `open/close_bracket`, `open/close_brace`),
  and symbols (`slash`, `backslash`, `apostrophe`, `asterisk`, `hash`,
  `numero_sign`, `percent_sign`, `ampersand`, `at_sign`, `plus_sign`,
  `minus_sign`, `equals_sign`, `underscore`, `vertical_bar`).
- **Editor/session**: `insert_template`, `save_draft`, `undo_last`,
  `stop_dictation`.
- **Typed-field commands**: `choice.set`, `choice.add`, `choice.remove`
  (see below).
- **Section navigation** (mechanism): a spec with
  `is_section_command: true` resolves the following 1–3 words against
  the active template's section names/aliases and emits
  `section.<section_id>` → `navigate_section`. If no section matches,
  the command is rejected and the words stay content.

Representative rows:

| Intent           | uk phrases                                       | en phrases                    | Pause | Conf |
| ---------------- | ------------------------------------------------ | ----------------------------- | ----- | ---- |
| `newparagraph`   | новий абзац, абзац, новий параграф               | new paragraph, paragraph break| 250   | 0.80/0.85 |
| `newline`        | новий рядок, перенос рядка                       | new line, line break          | 200   | 0.80/0.85 |
| `period`         | крапка, крапку                                   | period, full stop             | 300   | 0.80/0.88 |
| `comma`          | кома, кому                                       | comma                         | 250   | 0.80/0.88 |
| `save_draft`     | зберегти чернетку, зберегти як чернетку, зберегти| save draft, save as draft, save | 300 | 0.85 |
| `undo_last`      | відмінити останнє, скасувати останнє, скасувати  | undo last, undo that, undo    | 300   | 0.85 |
| `stop_dictation` | стоп диктування, зупинити диктування, …          | stop dictation, end dictation | 350   | 0.80/0.85 |
| `insert_template`| вставити шаблон, шаблон                          | insert template, template     | 300   | 0.80/0.85 |

German (`de`) plumbing exists throughout the matcher and pipeline, but
no German catalogue is currently seeded; a session with `language: "de"`
simply runs with an empty catalogue.

## Adding a new command

1. Edit `infra/postgres/seed/voice_commands_<lang>.json` — add a phrase
   list, pause threshold, confidence threshold, optional
   `is_section_command` / `is_option_command` / `exact_match_only`.
2. Run `make seed` (`scripts/seed/seed.py`; the JSON fixtures are
   AUTHORITATIVE — the seeder deletes every row for a language before
   re-inserting).
3. Add a test in `services/nlp-service/tests/unit/test_voice_command_matcher.py`
   covering the canonical phrase + at least one negative case, and a
   corpus row in `tests/fixtures/command_corpus_<lang>.py`.
4. If the command has a frontend operation, register it in
   `services/nlp-service/src/nlp_service/stages/operations.py`
   (a test enforces the 1:1 intent↔operation mapping against the seeds).

## Typed-field commands

Hands-free structured input: one utterance, zero taps. The option name
resolves against the **template's** `choice`/`multi_choice` sections,
and the operation carries the option **slug** — never the spoken words.

| Intent | uk | en | Operation | arg |
| --- | --- | --- | --- | --- |
| `choice.set` | обрати / вибрати / встановити `<опція>` | select / choose / set `<option>` | `set_choice` | `{section_key, value}` |
| `choice.add` | додати `<опція>` | add `<option>` | `add_choice` | `{section_key, value}` |
| `choice.remove` | прибрати / видалити `<опція>` | remove / delete `<option>` | `remove_choice` | `{section_key, value}` |

### Rules that make this safe

- **Exact option matching only.** The FSM never fuzzy-matches an option
  name. Fuzziness belongs in the extractor, where a wrong guess is a
  proposal the user can reject; a voice command **writes**, so a
  near-miss must never become a selection.
- **Exact heads for these specs** (`exact_match_only`). "прибрати"
  (remove) is Levenshtein-2 from "обрати" (set) — with the FSM's normal
  1-substitution tolerance, "remove email" would have selected it
  instead. Opposite actions must not be one typo apart.
- **A voice selection is `manual`, not `extracted`.** The user said
  it explicitly; nothing was inferred. The FE writes
  `field_specific_metadata.source = "manual"` (and therefore omits
  `confidence` — see the metadata contract).
- **Strict field semantics.** `add`/`remove` on a single-select section
  no-op with `reason: "not_a_multi_choice_section"` rather than being
  reinterpreted as `set`. `set` on a multi-select **replaces the whole
  selection** — a judgment call for predictability, cheap to revisit
  with rollout feedback.
- **An unrecognised option name is prose, not a no-op.** A no-op would
  still consume the command head, deleting a word from the note —
  "встановити пріоритет поки неможливо" must stay untouched. A `reason`
  no-op is emitted only when an option was positively recognised
  (`option_ambiguous`, `not_a_multi_choice_section`), so the FE can
  toast precisely.

Commands are stripped from the text by stage 1, so the field-extraction
stage never sees a command phrase — one utterance cannot both select
via voice and extract from the same words (test-enforced).

## Known false-positive sources

- **"слід" → `slash`** — FIXED. "слід" is Levenshtein-2 from "слеш",
  and "слід додати…" / "слід виключити…" are extremely common in
  Ukrainian prose, so the fuzzy match was inserting a stray "/" into
  notes. The `slash` spec is now `exact_match_only`. Found by the TP/FP
  corpus (`tests/fixtures/command_corpus_uk.py`).
- **"крапка над і"** — Ukrainian idiom; the pause-before gate (300 ms)
  catches the mid-phrase case.
- **"розділ"** as a content word — guarded by the section argument
  resolution: if no matching template section, the command is rejected
  and the word becomes content.
- **Paired open/close heads one edit apart** (e.g. German "Klammer
  auf"/"Klammer zu" when a German catalogue is seeded) must be
  `exact_match_only`, or the 1-substitution tolerance fires the
  opposite bracket.

## Frontend hand-off

Every `Final` message carries `voice_command: null` (default) or a
populated slot. The `operations` array always carries the
frontend-actionable derivative (see `operations.py`).
