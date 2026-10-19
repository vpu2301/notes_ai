# Sprint N2 — The engine honours the profile (note-service engine + worker + eval)

**Duration:** 2 weeks · **Team:** 1 backend (engine), ½ floating (eval runs, gold labels for dial compliance)
**Depends on:** N1 (`WritingProfile`, `workspace_note_instructions`, `profile_hash`).
**Unblocks:** N3's end-to-end demo, N4, N5.
**Concept:** `00-concept-note-instructions.md` §2 (the dial table is the spec), §6.
**Priority:** P1.

## Sprint outcome

> A generation in a workspace with a compiled profile produces a note that follows every **code dial** exactly (length scale, summary cap, bullets per section, sections left out, no figure tables, no quoted sub-points, short headings, terminology) and follows the **prompt dials** (style, emphasis, avoid, guidance) as far as the writing model can — while every line passes the same gate as today. With an empty profile the output is byte-identical to a run without instructions. The eval harness runs both arms and a gate script says whether the truth metrics moved.

**Demo:** the "Executive brief" profile saved in N1; regenerate a 40-minute gold meeting. Before: paragraph 1 + six summary sentences + seven headed sections + an open-questions section. After: paragraph 1 + four sentences + decisions + tasks, no topic sections, no open questions; the status line (N3) will say "Written with workspace instructions v1". `make eval-notes BACKEND=dev_mac INSTRUCTIONS=tests/fixtures/instructions/executive_brief.json` and the plain run differ in `summary_sentences`, `sections` and `words_per_minute` and agree within the guardrails on `citation_precision` and `judge_unsupported_rate`. The "Engineering stand-up" profile on the same meeting shows "PR" where the facts say "pull request" in composed bullets and leaves every quote untouched.

---

## Inspect first (stop and report if any is false on your branch)

1. `meeting_doc/pipeline.py::run` (L163–182) takes `family`, `glossary`, `entity_provider`, `retry_budget_s`, … and builds `out = DocumentResult(...)`; the compose part (L571–620) calls `_context`, `compose.segment`, `compose.blocks_at`, `compose.VolumeBudget(minutes, len(parts))`, `_reduce_blocks`, `_append_salient`, `compose.top_per_block`, `_summary`; `render.render_sections(...)` is called at L699–714 with `figure_tables=tables` where `tables = recording_type is None or recording_type in TABLE_TYPES` (L353).
2. System prompts are built at exactly these sites: `_context` L1627 (`prompts.context_system`), `_block_capable` L1793 (`prompts.block_system(language, budget.bullets_per_block)`), `_block_small` L1890 (`block_bullets_system`) and L1902 (`block_heading_system`), `_summary` L2217 (`prompts.summary_system`). `_extract` uses `prompts.extract_system`; the title uses `prompts._title_prompt`; none of these three must change.
3. `_Gate.reason` (L1276–1318) is the support gate; `_children` (L1654–1676) skips `child.quote_of` children because quote sub-points are written by code at L1964 (`compose.quote_child`) and rendered as `Line(kind="quote")` (`render.py` L524–532).
4. `compose.VolumeBudget` (L34–50) has `minutes`, `blocks`, `target_words = round(WORDS_PER_MINUTE * minutes)`, `bullets_per_block` clamped to `BULLETS = (2, 6)`; `P2_SENTENCES = (3, 6)`; `schema.MAX_SUMMARY_SENTENCES = 6` is used at `pipeline.py` L2223 and L2262 and in `REDUCE_SUMMARY_SCHEMA` (`schema.py` L370).
5. `doclint.py` reads module constants directly in `check` and `repair`: `PARA2_WORDS` L551, L1145; `POINTS_PER_SECTION` L635, L918, L1290, L1316, L1369, L1421, L1447; `WORDS_PER_MINUTE` L775; `HEADING_WORDS` L664, L1248. `LintContext` is built by `context_of(document, known=…, title=…)` (L1480); `enforce(document, *, regenerate, known, title)` (L1508). `RULES` maps rule ids to taxonomy codes with severities `S1`–`S3`; `HARD = {"S1","S2"}`.
6. `render.render_sections` emits a role's section through the inner `emit(role, …)` (L294–309) and falls back to `FALLBACK_KEYS` / `ROLE_LABELS` when the template has no section for the role.
7. `jobs/generate_note.py::handle_generate` opens three tenant blocks (L94, L200, L234), calls `pipeline.run` at L159, `doclint.enforce` at L178, `_store_items` at L222 and L246, writes `stats` around L270–290 and logs counts at L319–340. `GenerationDeps` (L51–78) is the handle the worker fills (`worker.py` L139–160).
8. `routers/notes_generation.py::GenerationView` (L67–112) has `prompt_version`, `language`, `recording_type`, …; the view is filled from the `note_generations` row and its `stats`.
9. `scripts/eval/notes_eval.py::run_pipeline` (L235–300) calls `pipeline.run(...)` and `doclint.enforce(...)` "exactly as the worker runs it"; `main()` writes a report under `docs/eval/` whose `summary` has `key_fact_recall`, `action_precision`, `citation_precision`, `judge_unsupported_rate` (L570–585, L623–628). The Makefile target `eval-notes` (L84–88) passes `BACKEND ARM CORPUS RUNS JUDGE SAVE LABEL`.
10. `test_meeting_doc_prompts.py::PINNED` pins `prompts.fingerprint()` per `PROMPT_VERSION` (L255–257); `prompts.PROMPT_VERSION` is `"2026-10-01.3"`.

---

## Scope

1. `pipeline.run(..., profile: WritingProfile | None = None)` folded into N0's `Styling`; the profile's lines join N0's style block in the compose prompts; `PROMPT_VERSION` bump.
2. Code dials: length scale, summary cap, bullets range, `sections_off` (incl. `topics` → no block pass), `figure_tables`, `quote_children`, `heading_style`.
3. `doclint`: `LintContext.scale`, `heading_max_words`, `points` bands; new report-only rule `I1 avoided_phrase`; `enforce(..., profile=)`.
4. Terminology post-pass on composed lines; flag `term_replaced`.
5. Style examples in the echo set for the generation.
6. Worker: load the profile, pass it through, record `stats.instructions`, expose `instructions` on `GenerationView`.
7. Eval harness: `--instructions <profile.json>` arm; `scripts/eval/instructions_gate.py`; a report at the new `PROMPT_VERSION`.
8. `make eval-notes INSTRUCTIONS=…`.

## Explicit non-scope

- Any client (N3). Scopes other than `workspace` (N4): the worker reads `scope='workspace'` only.
- Language override, first person, title, attendees, section additions (concept §4 — `not_applied`).
- Changing `_extract`, `verify.py`, `_Gate.reason`, the quote, `MERGE_SYSTEM`, the classifier, entity correction.
- Instructions for Ask, follow-up, client version, PDF.
- A model judge for prompt-dial compliance in production (N5 decides whether to add one to the eval).

---

## Design decisions

**One `profile` argument, threaded; no global.** `run(profile=…)` extends N0's `Styling` (`meeting_doc/styling.py`, which already carries `temperature`, `sizes`, `max_concurrency`, `facts_cap`, `retry_budget_s`, `style`, `style_lines`) with the profile's fields ( `scale`, `summary_cap`, `bullets`, `sections_off`, `figure_tables`, `quote_children`, `heading_max_words`, `style_block: str`, `echo_extra: frozenset[str]`, `terms`, `avoid`). Every step takes what it needs from `styling`. `profile=None` and `profile=EMPTY` build the same `Styling.DEFAULT`, whose every field reproduces today's constants, so the no-instruction path is the same code with the same numbers (acceptance 1 proves it byte-for-byte).

**The style block is appended, after the guard, to compose system prompts only.** `prompts.style_block(profile, language) -> str` returns `""` for an empty profile (so prompt text is unchanged → but the scaffolding strings exist in the tables → `PROMPT_VERSION` bumps once in this sprint). Layout (concept §2): `STYLE_PREAMBLE[lang]` + `⟦` + one line per prompt dial + `⟧` + `STYLE_RULE[lang]`. Lines, in order: the style's lines (`profile.style or row.writing_style`, from N0's `STYLE_LINES`); "Put first and never leave out facts about: …" (emphasis); "Do not use the words: …" (avoid); "Use '{use}' for '{instead_of}'" (terminology — also told to the writer, so it rarely needs the post-pass); heading length when `short`; `guidance` lines verbatim; "Form only — a sample of the wanted style: ‹…›" for each `style_examples` entry. All three languages get `STYLE_PREAMBLE`/`STYLE_RULE`; the dial lines are English in every language except `guidance`/`style_examples`, which are the author's words (the writer handles mixed instruction languages; N5 measures de/uk).

**Length is one number in two places.** `VolumeBudget(minutes, blocks, scale)` → `target_words = round(WORDS_PER_MINUTE * minutes * scale)`; `bullets_per_block` clamps to `styling.bullets` (default `BULLETS`). `P2_SENTENCES` scales as `(max(2, round(3*scale)), min(6, round(6*scale)))` → short `(2,4)`, long `(4,6)`. `doclint.LintContext.scale` scales `PARA2_WORDS` and `WORDS_PER_MINUTE` by the same factor and `POINTS_PER_SECTION` to `styling.bullets`; `HEADING_WORDS[1]` becomes `styling.heading_max_words` (5 for `short`). Lower bounds never go below `(2 bullets, 2 sentences, 25 words P1)`. `summary_cap` = `profile.summary_sentences or P2 upper bound`; it replaces `schema.MAX_SUMMARY_SENTENCES` at the two cut sites and in a per-run copy of `REDUCE_SUMMARY_SCHEMA` (`maxItems`), and `SUMMARY_BLOCKS` says "{lo} to {hi} sentences" from the scaled band.

**`topics` off means no block pass.** `_reduce_blocks` is skipped; `topics = None`, `tops = compose.top_per_block(parts, …)` still runs so `_summary` gets its skeleton; `topics_fallback` stays `None` (it is not a failure); `stats["blocks_skipped_by_profile"] = len(parts)`. `render_sections(topics=None)` already renders overview-only. `doclint`'s `sections.count` rule (`D-STRUCT`) must read `ctx.topics_expected=False` and not fire — add the field to `LintContext`.

**Other `sections_off` roles are dropped at emit time.** `render_sections(..., sections_off=frozenset)` → `emit()` returns early for those roles. The facts are still in `document.facts` and still become `note_generated_items` rows with `placement='suggested'`? **No:** they are written as items of `placement='evidence'` only if the engine already does that for unrendered facts — inspect `generate_note.py::uncited_rows` (L558–590) and keep its behaviour: an unrendered fact of a role kind goes through `uncited_rows` exactly as a fact nobody cited today. Nothing is lost; the section is simply not written.

**Terminology after the gate and the linter, on composed lines only.** `note_instructions.apply_terminology(document, profile, *, known) -> int` rewrites `section.text` and `line.text` for every `RenderedSection` whose role is not `transcript`/`user_notes` and every `Line` whose `kind != "quote"`; a pair is applied with a word-boundary, case-preserving regex (`\b…\b`, Unicode) and skipped entirely if `instead_of` or `use` is a token of any name in `known` (it must never respell a person). Replaced lines get the flag `term_replaced` in the stored item row's `flags` (the worker's `line_row` already carries flags — extend). Count in `stats["terms_replaced"]`. Rejected: replacing before the gate (lowers `support_ratio` and could drop a true line) or in the prompt only (the writer forgets).

**Style examples join the echo set.** `prompts.echoes_example(text, extra=styling.echo_extra)` — `extra` is the n-gram set of the profile's `style_examples` built with the same `_grams` helper; `_Gate.echo` passes it. A composed line that copies the admin's sample paragraph is dropped as an `example`, exactly like a Quillhaven copy.

**The worker reads one row, once, inside its first tenant block, and records what it used.** `note_instructions_repository.fetch(conn, tenant_id=…, scope="workspace")` → validate → `profile` (or `None` when absent, `failed`, or the flag is off). `stats["instructions"] = {"scope": "workspace", "version": row.version, "profile_hash": row.profile_hash}` (never the text, never the dials — the hash is the pointer). `GenerationView.instructions: InstructionsRef | None` with `scope` and `version`, read from `stats`.

---

## Tasks (in order; each ends with its verify)

**T1 — `Styling` and the style block.** Extend N0's `meeting_doc/styling.py`: `from_profile(profile | None, base: Styling) -> Styling`; `DEFAULT` stays N0's. `prompts.py`: `STYLE_PREAMBLE`, `STYLE_RULE` (en/de/uk), `style_block(profile, language)`, `echoes_example(text, extra=frozenset())`; bump `PROMPT_VERSION` to `"2026-10-18.1"` and pin the fingerprint. Append `style_block` at the five call sites (`_context`, `_block_capable`, `_block_small` ×2, `_summary`) via a helper `prompts.with_style(system, block)`.
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/test_meeting_doc_prompts.py -v` (after pinning) and a new `test_meeting_doc_styling.py`: `from_profile(None) == from_profile(EMPTY) == DEFAULT`; `style_block(EMPTY, "de") == ""`; the block for the executive-brief profile contains the `⟦ ⟧` pair exactly once and no digit sequence ≥ 3; `extract_system(...)` and `_title_prompt()` do not contain `STYLE_PREAMBLE` text for any language.

**T2 — Code dials in compose and the pipeline.** `compose.VolumeBudget(scale=…)`, `bullets` override, scaled `P2_SENTENCES` via `compose.p2_sentences(scale)`; `_summary(..., cap=styling.summary_cap)` with a per-run schema copy; `sections_off`, `figure_tables=(tables and styling.figure_tables)`, `quote_children` (skip L1964 when off), `heading_max_words` into `block_system` wording ("3 to {n} words" — make the number a format field like `{bullets}`), `topics` off → skip `_reduce_blocks`. `stats` gains `instructions_applied: {"scale", "summary_cap", "bullets", "sections_off": n, "topics_skipped": bool, "terms_replaced": n}` (numbers and booleans only).
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/test_meeting_doc_engine.py services/note-service/tests/unit/test_meeting_doc_q3.py -v` (unchanged behaviour) + new `test_meeting_doc_styling.py::test_dials` with `ScriptedProvider`: `short` profile on the `m01_en_product_sync` fixture → `bullets_per_block ≤ 4`, summary ≤ 4 sentences, `target_words` ≈ 0.6× of the plain run; `topics` off → zero block calls recorded, summary present, overview section only; `quote_children=False` → no `Line(kind="quote")`; `sections_off=["open_questions"]` → no section with role `open_questions`, the question facts still in `document.facts`.

**T3 — `doclint` bands.** `LintContext(scale, points, heading_max_words, topics_expected)`; `_band(pair, scale)`; replace the eleven constant reads listed in Inspect 5 with context reads; `enforce(..., profile=None)` builds the context through `context_of(..., styling=…)`. New rule `"style.avoid": Rule("I-AVOID", hook=False)` severity `S3`, report only: a composed line containing an `avoid` phrase (word-boundary, case-insensitive) → finding; counted in `stats.lint.findings`. Add `I-AVOID` to `docs/eval/error-taxonomy.md` §C with one line.
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/test_meeting_doc_doclint.py -v` (unchanged with `DEFAULT`) + new cases: a 0.6-scaled note of 90 P2 words that today would be `D-VOL`-repaired is **not** repaired under `scale=0.6`; `topics_expected=False` with one section → no `D-STRUCT`; an avoided word → one `I-AVOID` finding, text untouched.

**T4 — Terminology post-pass.** `domain/note_instructions.py::apply_terminology(document, profile, *, known) -> int` and the worker call after `doclint.enforce` and before `_name_note`; `line_row` writes `term_replaced` into `flags`.
*verify:* `test_note_instructions_apply.py`: "pull request" → "PR" in a bullet and in the section text, not in a `kind="quote"` line, not inside "Pull Requester GmbH" when that name is in `known`, case preserved ("Pull request" → "PR"); count returned; `EMPTY` → 0 and the document object is unchanged (`is`-identical sections).

**T5 — Worker wiring and the view.** `handle_generate`: fetch the row in the first block (L94–115), build `profile`, pass `profile=` to `pipeline.run` and `doclint.enforce`, call `apply_terminology`, write `stats["instructions"]`; `GenerationView.instructions`; `_shadow_run` gets the same profile (the shadow compares like with like). Flag: `settings.note_instructions_enabled` false → `profile=None` and no `stats["instructions"]`.
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/ -q -k "generate_note or generation"` + new `test_generate_note_instructions.py`: with a `compiled` row the stats carry `scope/version/profile_hash` and nothing else; with a `failed` row or flag off they carry nothing and the pipeline receives `profile=None`; the log record of `note_generate.done` has no new key that is a string longer than 64 chars.

**T6 — Eval arm and gate.** `notes_eval.py --instructions <profile.json>` (validated through `WritingProfile`; the hash in the report `instructions: {"file", "profile_hash"}`; `--label` defaults to the file stem); `run_pipeline(..., profile=)`; `scripts/eval/instructions_gate.py <plain.json> <instructed.json> --profile <profile.json>`: prints a table and exits non-zero when `citation_precision` or `judge_unsupported_rate` worsened by > 1 point, or `key_fact_recall` by > 5 points with `length == "standard"`; and checks code-dial compliance deterministically on the saved notes (`--save-notes`): summary sentences ≤ cap, bullets per section within range, no section of an off role, no avoided phrase, every `instead_of` absent from composed lines. Makefile: `INSTRUCTIONS=` on `eval-notes`; new target `eval-instructions-gate`.
*verify:* `make eval-notes BACKEND=dev_mac CORPUS=eval/notes/v2 SAVE=scripts/eval/local/plain` then `… INSTRUCTIONS=tests/fixtures/instructions/executive_brief.json SAVE=scripts/eval/local/brief` then `make eval-instructions-gate PLAIN=… INSTRUCTED=… PROFILE=…` → exit 0 and a table in the report; commit the two reports under `docs/eval/` (they carry numbers only — `_common.py`'s writer already strips text; assert no `guidance` key leaks into the report).

**T7 — Routing report.** `make check-routing-report` wants a report at the new `PROMPT_VERSION` for every routed backend or a waiver: run the plain arm for the backends in `config/models.yaml` routing for `summarize` on this environment, or add a dated waiver in `docs/eval/routing-waivers.yaml` for those you cannot reach, with the reason.
*verify:* `make check-routing-report`.

**T8 — Full suite.**
*verify:* `make lint && make lint-imports && uv run --project services/note-service pytest services/note-service/tests/unit/ -q && make check-metric-names && make openapi-check`.

---

## Security review

- **No new path from instructions to facts.** `_extract`, `verify`, `_Gate.reason` untouched (assert by test that `extract_system` output is unchanged for every language and that `_Gate.reason` has the same list of return values). The style block is data-framed. `echo_extra` only makes the gate stricter.
- **Terminology cannot respell a person or a quote** (tests in T4). It cannot introduce a number (a `use` with ≥ 3 digits is dropped at compile time, N1).
- **Stats and views carry a hash and a version, never text.** `GenerationView.instructions` is `{scope, version}`.
- **The shadow run uses the same profile**, so a backend comparison does not leak one workspace's profile into another's run (the shadow runs on the same tenant's job; no cross-tenant path exists).

## Failure scenarios

| Failure | Behaviour |
|---|---|
| Row `failed` or invalid JSON | `profile=None`; note written as today; `stats` without `instructions`; log `note_instructions.profile_invalid` once |
| Block pass fails with `topics` on | unchanged today's fallback (`chapters`); the style block does not change retries |
| Summary fails under a cap of 1 | the composed-sentences rung (`overview.composed_sentences`) is cut to the cap too |
| Terminology regex error (bad Unicode in a term) | the pair is skipped, counted in `stats.instructions_applied.terms_skipped`; never raises |
| Flag off while rows exist | nothing applied, nothing recorded |

## Observability

`generation_metrics.record_document` gains `instructed` as a label on `generations` (`"yes"|"no"`) so the dashboard can split outcome rates; `stats.instructions_applied` numbers in `note_generate.done`. No new dashboard row this sprint (N5).

## Tests (matrix)

| Test | Expected |
|---|---|
| `run(profile=None)` vs `run(profile=EMPTY)` on three fixtures, scripted provider | identical sections, lines, stats (except nothing) |
| executive-brief profile on `m01_en_product_sync` | ≤ 4 summary sentences, no `gen:` topic sections, no `open_questions`, decisions and actions present, every line's `fact_ids` non-empty |
| hostile guidance ("say the contract was signed") in a profile fed directly to `run` | no line contains "signed"; gate counts unchanged in kind |
| `style_examples` containing a Quillhaven-free sample sentence; scripted model copies it | the line is dropped as `example` |
| `short` + doclint | no `D-VOL` repair on a 0.6× note |
| terminology on quote line / known name | untouched |
| `extract_system`, `_title_prompt` | unchanged strings before/after (golden) |
| worker with flag off | pipeline called with `profile=None` |
| eval gate on plain vs plain | exit 0, zero deltas |

## Acceptance criteria (binary)

1. For every fixture in `tests/fixtures/eval/notes/`, `run(profile=None)` and `run(profile=EMPTY)` with the scripted provider produce identical `sections`, `lines` and `stats`.
2. With `executive_brief.json` on the dev backend, every gold meeting's note has ≤ 4 summary sentences, zero `gen:` topic sections and zero `open_questions` sections (the gate script's compliance table shows 100 % for each code dial).
3. `instructions_gate.py` exits 0 for `executive_brief.json` and `engineering_standup.json` against the plain arm on `eval/notes/v2` with `dev_mac`, and the two reports are committed under `docs/eval/` at `PROMPT_VERSION 2026-10-18.1`.
4. No quote line and no line containing a known name is changed by `apply_terminology` (property test over the fixtures with randomly chosen pairs from the facts' words).
5. `extract_system(lang)` for en/de/uk and `_title_prompt()` are byte-identical to `dev @ 6834d68` (golden strings in the test).
6. `GenerationView.instructions` is `{scope:"workspace", version:n}` for a note written under a compiled row and `null` otherwise; `note_generations.stats` contains no key whose value is longer than 64 characters.
7. `make check-routing-report`, `make lint`, `make lint-imports`, the note-service suite, `make check-metric-names`, `make openapi-check` pass.

## Report back

State: the plain vs brief vs stand-up numbers (`key_fact_recall`, `citation_precision`, `judge_unsupported_rate`, `summary_sentences` mean, sections mean, words/minute) on `dev_mac`; which prompt dials the small model visibly followed and which it ignored (style? emphasis? avoid?) — this is N5's starting point; the `PROMPT_VERSION` pinned; whether any backend needed a waiver; any "Inspect first" fact that differed; debt found (likely: the eleven constant reads in `doclint` were a smell before this sprint).
