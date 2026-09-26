# Sprint Q1 — Measure first

**Services:** `scripts/eval/`, `services/note-service` (`domain/meeting_doc/prompts.py`, `pipeline.py`, tests), `tests/fixtures/eval/notes/`, `.github/workflows/`. **No migration, no route, no UI.** **Length:** 1 week. **Priority:** P0 — nothing in Q2–Q5 may start until this sprint's numbers exist.

## Goal

Every metric in the audit has a number, for our engine and for the single-pass baseline, produced by a harness that feeds the engine the same shape the worker feeds it. The "November" sentence cannot be produced again, and a test proves that a run's prompts contain nothing but its own recording. A nightly job keeps the numbers current.

```
make eval-notes BACKEND=dev_mac ARM=pipeline     CORPUS=eval/notes/v2   # ours
make eval-notes BACKEND=dev_mac ARM=single_pass  CORPUS=eval/notes/v2   # the baseline to beat
make eval-notes BACKEND=dev_mac ARM=pipeline     JUDGE=dev_mac          # + model judge column (eval only)
make eval-notes-assert CORPUS=eval/notes/v2                             # regression checklists (r01 = ZEIT)
```

## Inspect first (checked on `summaries` @ `fbba745`, 2026-09-22 — confirm, then code)

| # | Fact | Where |
|---|---|---|
| 1 | `as_asr_result` emits `turns: [{speaker, start_ms, end_ms, text}]`. `turns_from_result` reads `raw.get("paragraphs")` and `raw.get("name")`; a turn without `paragraphs` is skipped; with no turns it falls back to `segments`, which the harness does not emit. Running the harness shape through `turns_from_result` yields **0 turns**. | `scripts/eval/notes_eval.py` L169–183; `meeting_doc/windows.py` L98–121 |
| 2 | `run_pipeline` calls `pipeline.run(as_asr_result(meeting), provider=…, role_by_key={}, language=…, family=…)` — no `meeting_date`, no `name_candidates`, no roles. `single_pass` is a separate arm with one prompt. | `notes_eval.py` L189–247, L248–293 |
| 3 | Scoring: `words()`/`overlap()` content-word overlap ≥ 0.6 (`MATCH_THRESHOLD` L50); `score()` L294–365 produces key_fact_recall, action recall/precision, decision recall/precision, owner_accuracy, citation_precision; `summarise()` L366–383 adds window_failure_rate, seconds_per_meeting_hour, tokens. A hallucinated quote exits 1 (L447–449). | `notes_eval.py` |
| 4 | Reports go to `docs/eval/notes-<arm>-<date>-<backend>.json` via `_common.write_report(kind, backend, payload, suffix=)`; payload carries `PROMPT_VERSION`, git sha, host info. Numbers and ids only. | `scripts/eval/_common.py` L57–71 |
| 5 | Gold fixture format (v1): `{id, language, meeting_type, transcript:[{speaker,t_start_ms,t_end_ms,text}], gold:{key_facts, actions:[{text,owner}], decisions, open_questions}}`. Five synthetic files `m01`–`m05`. The real corpus `eval/notes/v1` is in the eval bucket, passed with `--corpus`. | `tests/fixtures/eval/notes/README.md` |
| 6 | Content-bearing example sentences in prompts: extraction shots L177–225 ("November launch", "pricing deck", "two million"); `EXTRACT_SYSTEM` L86–87 / L127–128 / L163–164 ("Sanctions against Russia remain limited by enforcement gaps" in three languages); `REDUCE_SUMMARY_SYSTEM` L287–288 / L299–300 / L313–314 ("The November launch remains the target" / „Der Start im November bleibt das Ziel“ / «Запуск у листопаді лишається метою»); `REDUCE_CONTEXT_SYSTEM` L331–333 / L346–348 / L361–363 ("Interview with a defence expert on the war in Ukraine…"), and the conversation-type example lists at L327 / L342 / L357–358 (meeting types before podcast/lecture). | `meeting_doc/prompts.py` |
| 7 | `_summary` keeps a sentence when it cites ≥ 1 known fact id and `_numbers_supported`; `_topics` keeps a bullet when it cites ≥ 1 known id; `_context` number-checks only the framing. No other content check exists on reduce output. `PROMPT_VERSION = "2026-10-5"`. | `pipeline.py` L357–446; `prompts.py` L30 |
| 8 | `DocumentResult` has `sections`, `facts`, `windows_*`, `failed_ranges`, `stats`, `brief` (`conversation_type`, `subject`, `themes`, `key_fact_ids`), `noise: [(start_ms, reason)]`. Sections carry `facts` per **section**, not per line (`render.RenderedSection`). Summary sentences and topic bullets lose their `fact_ids` after `_summary`/`_topics` return (`list[str]` and `list[tuple[str, list[str], list[str]]]`). | `pipeline.py` L67–96, L357–435; `render.py` L187–197 |
| 9 | `windows.thirds(windows)` gives the third of the meeting each window is in; facts carry `window_index`. | `windows.py` L232–248; `verify.VerifiedFact.window_index` |
| 10 | Stop-word list and tokeniser used for merging: `merge.py` L37–96 (`_tokens`, NFKC + casefold, words > 1 char). | `meeting_doc/merge.py` |
| 11 | Engine tests build fakes ad hoc (`class _Provider` with `complete(prompt, schema=None, **kwargs)`), and there is no shared scripted provider for a whole `pipeline.run`. Harness tests live in `tests/unit/test_notes_eval.py`. | `services/note-service/tests/unit/test_meeting_doc_engine.py` L1406; `tests/unit/test_notes_eval.py` |
| 12 | The nightly DER job runs on the self-hosted runner `[self-hosted, macOS, mdx-eval]`, syncs with `uv sync --all-packages`, compares to committed baseline reports with `MAX_DROP`, and is the pattern to copy. | `.github/workflows/nightly-der.yml` |
| 13 | `scripts/eval/local/` is the gitignored place for real transcripts (Sprint G1 T11). Confirm it is in `.gitignore`; add it if not. | `.gitignore` |

## Out of scope

Any change to `verify.py`, `windows.py`, `render.py` or the worker (Q2–Q3). New fact fields other than the ones T3 names. Human rating (Q4). Native clients. A production model judge. Collecting any competitor's output (concept §6).

---

## Tasks

### T1 — The harness feeds the engine what the worker feeds it

`scripts/eval/notes_eval.py`:

1. `as_asr_result` emits the result-view shape the worker snapshots: `turns: [{speaker, name, start_ms, end_ms, paragraphs: [text]}]`, `speaker_names: {label: name}` from `gold.speakers` when present (else `Speaker N` from the label, as `default_speaker_name` does), `name_candidates: gold.name_candidates or []` (the result-view field name, `libs/asr_models/src/asr_models/output.py` L271), `language`, `result_rev: 1`, and — new, optional in the fixture — `recorded_on: "YYYY-MM-DD"`.
2. `run_pipeline` passes `meeting_date=date.fromisoformat(meeting.get("recorded_on") or "2026-01-15")`, `name_candidates=frozenset(result["name_candidates"])`, and `role_by_key` read from the seed template `meeting_notes[_<lang>]` (`infra/seeds/templates/*.json`, role field on sections — same function the worker's `_role_map` uses if it is importable without a DB; otherwise a small local reader of the seed file). The document must land in the sections production lands it in.
3. After `pipeline.run`, if `document.windows_total == 0` and the transcript is non-empty: print `engine saw no transcript` and exit 2. This is the bug that hid everything; it must be loud.
4. `produced` gains `lines` (T3) and `document.stats` verbatim.

Tests (`tests/unit/test_notes_eval.py`): `turns_from_result(as_asr_result(m02))` has as many turns as the fixture has transcript entries; names resolve; exit code 2 on a zero-window run with a fake provider.

**verify:** `uv run --project services/note-service pytest tests/unit/test_notes_eval.py -v`

### T2 — Gold format v2 and a validator

Extend `tests/fixtures/eval/notes/README.md` and add `scripts/eval/notes_gold.py` (pydantic models, `validate_corpus(path) -> list[str]` of problems, `python scripts/eval/notes_gold.py <corpus>` prints them; Makefile target `eval-notes-validate`). All new fields optional so v1 files stay valid:

```json
"recorded_on": "2026-09-22",
"recording_type": "meeting|client_call|sales_call|interview|one_on_one|podcast_broadcast|lecture_webinar|voice_memo",
"gold": {
  "key_facts": [...], "actions": [...], "decisions": [...], "open_questions": [...],
  "entities":  [{"canonical": "Friedrich Merz", "surface_forms": ["Friedrich Schmerz", "Merz"], "kind": "person|org|place|product"}],
  "hedged":    [{"fact": "Aus für Rente mit 63 wird abgeschwächt", "modality": "forecast|estimate|plan|unconfirmed|opinion"}],
  "dates":     [{"text": "am Montag", "resolved": "2026-09-21", "tense": "past|future|none"}],
  "speakers":  {"SPEAKER_1": "Imre Balzer"},
  "name_candidates": ["Imre Balzer", "Fabian Reinbold"],
  "topics":    [{"title": "…", "t_start_ms": 0}],
  "must_contain": ["…"], "must_not_contain": ["November", "Teambesprechung"]
}
```

Validator rules: every `surface_form` and every `dates[].text` occurs in the transcript; `speakers` keys occur as transcript speakers; `must_not_contain` strings do **not** occur in `key_facts` (a gold fact containing a forbidden string is a contradiction); `recording_type` in the enum.

Add `m06_de_news_podcast.json`: synthetic, invented names and outlet, German, ≈ 7 minutes, shape of the ZEIT episode — a host, a correspondent, one sound bite of a third person, two stories with a cue-phrase switch, an estimate ("wahrscheinlich"), two mangled surface forms, "heute", "am Montag … gewesen", "bis Mittwoch 0 Uhr", a number (≈ 3 000), a deadline. `recording_type: podcast_broadcast`, `meeting_type: auto`, `recorded_on` a Tuesday. Add `m07_uk_lecture.json` (lecture, no actions, one open question) and `m08_en_one_on_one.json` (feedback, one explicit action with a date).

**verify:** `python scripts/eval/notes_gold.py tests/fixtures/eval/notes` prints nothing; the `test_notes_gold.py` unit tests pass.

### T3 — Line-level provenance in the engine (additive, no behaviour change)

`meeting_doc/pipeline.py`:

- `_summary` returns `list[tuple[str, list[str]]]` (sentence, cited ids); `_topics` bullets become `list[tuple[str, list[str]]]`. `render.render_sections` accepts these shapes and **renders exactly what it renders today**.
- `RenderedSection` gains `lines: tuple[Line, ...]` where `Line(text, kind, fact_ids)`; `kind ∈ {framing, summary, key_point, bullet, decision, action, question, risk, next_meeting, agenda, note}`. Every rendered line of every section is in `lines`, in order. `section.text` is unchanged.
- `DocumentResult.lines` = all sections' lines with `section_key`. `DocumentResult.noise_ranges: list[tuple[int, int, str]]` = `(start_ms, end_ms, reason)` per flagged turn (the turn's own end). `noise` stays for compatibility.
- `VerifiedFact.certainty: str | None` — carried from `Fact.certainty` (D-2). Nothing renders it yet.

Tests: a rendered document's `lines` texts, joined per section, equal `section.text` line for line; every `summary`/`bullet`/`framing` line cites ≥ 1 id; snapshot test of `render_sections` output on a fixed fact list before and after this task (byte-identical).

**verify:** `uv run --project services/note-service pytest services/note-service/tests/unit/test_meeting_doc_engine.py -v`

### T4 — Prompts without content; example-phrase guard; own-recording test

`meeting_doc/prompts.py`:

1. Replace every example sentence in fact 6 with examples from one deliberately synthetic domain that no business recording will be about — the seed vocabulary is a fictional board game company ("Quillhaven", product "Ferrytale", the "Lantern edition"). Examples must still show the four negative cases (proposal ≠ decision, "we should" has no owner, worry → risk statement, estimate stays estimate) and the type list of the context prompt must **not** start with a meeting type: use the neutral order `podcast, interview, lecture, team meeting, sales call, one-on-one`.
2. Export `EXAMPLE_PHRASES: Final[frozenset[str]]` — every content 4-gram (normalised as `verify.normalise_quote`) of every example sentence and the two proper nouns, in all three languages. Build it from the same strings the prompts use (one source of truth), not a hand-copied list.
3. `PROMPT_VERSION = "2026-10-6"`.

`meeting_doc/pipeline.py`: in `_summary`, `_topics` and `_context` (framing), drop any line whose normalised text contains an `EXAMPLE_PHRASES` entry; count `stats["example_echo_dropped"]`. Also in `verify_facts`: a fact whose `text` contains one is dropped (`stats.dropped_example`).

Tests (`tests/unit/test_meeting_doc_prompts.py`, new):

- `test_no_example_phrase_appears_in_any_fixture`: for every JSON under `tests/fixtures/eval/notes/` and `tests/fixtures/meeting_doc/`, no `EXAMPLE_PHRASES` entry occurs in the transcript. (If a synthetic fixture legitimately trips this, change the fixture, not the set.)
- `test_an_echoed_example_never_reaches_the_note`: scripted provider returns the German example sentence as a summary sentence citing a real id → the overview does not contain it; `stats["example_echo_dropped"] == 1`.
- `test_prompts_carry_only_this_recording` (the P0-1 closure test): `ScriptedProvider` (new shared fake in `tests/unit/meeting_doc_fakes.py`: keyed by which schema it receives — extract / context / topics / summary — returns canned JSON, and **records every prompt and system string**). Run `pipeline.run` on fixture A. Assert: every `⟦…⟧` block in an extract prompt is a substring-set of fixture A's window renderings; every `⟦…⟧` block in a reduce prompt contains only ids and texts of facts produced in this run; no system string contains a 4-gram of fixture B's transcript. Run again on fixture B in the same process: no prompt contains a 4-gram of fixture A's transcript (no state leaks between runs).
- `test_prompt_version_changes_with_prompt_text`: sha256 of the concatenated prompt tables is pinned next to `PROMPT_VERSION`; a change to either without the other fails.

Write `docs/security/2026-09-22-november-sentence.md` (≤ 1 page): symptom, trace (fact 6, fact 2b in the concept), conclusion *not an isolation incident*, the guard added, the test that keeps it closed.

**verify:** `uv run --project services/note-service pytest services/note-service/tests/unit/ -v && make lint`

### T5 — Scorers for every audit metric

New `scripts/eval/notes_scoring.py` (pure functions; the harness calls them; unit-tested with hand-built inputs). Inputs: the gold dict, `produced` (`lines`, `facts` as dicts with `item_key`, `text`, `quote`, `certainty`, `start_ms`, `window_index`), `document.stats`, `document.brief`, `noise_ranges`.

| Metric | Function | Rule |
|---|---|---|
| `unsupported_rate` | `support(line, cited_facts)` | content tokens of the line (merge's tokeniser + stop list; tokens > 5 chars stemmed to their first 5) found in the cited facts' `text + quote` ÷ line content tokens. Supported when ≥ 0.5 **and** every number in the line is in a cited fact (`verify._NUMBER`) **and** every capitalised token of the line (`verify._CAPITALISED`) is in a cited fact or is sentence-initial. Rate = unsupported lines ÷ lines of kind `framing|summary|bullet`. |
| `invented_claims` | over all lines | lines with a number or capitalised non-initial token absent from **every** verified fact of the run. Count, not rate. |
| `example_echo` | | lines containing an `EXAMPLE_PHRASES` entry. |
| `key_fact_recall` | existing | unchanged (overlap ≥ 0.6 against all lines). |
| `coverage_ratio` | | recall computed per third of the transcript (gold fact matched to a line whose cited facts' `window_index` falls in that third, via `windows.thirds`); worst ÷ best. |
| `excluded_speech` | | Σ duration of `noise_ranges` ÷ Σ transcript turn durations. |
| `recording_type_acc` | | `brief.conversation_type` mapped through a small alias table (`Teambesprechung|team meeting → meeting`, `Podcast|Nachrichten → podcast_broadcast`, …) == `gold.recording_type`. Q3 replaces the source with `stats.recording_type`. |
| `redundancy` | | pairs of lines (all kinds, all sections) with token Jaccard ≥ 0.6; rate = lines that are in ≥ 1 such pair ÷ lines. |
| `entity_accuracy` | | for each gold entity: the canonical (or its last token) occurs in the lines and no surface-form-only spelling occurs. Reported twice: all entities, and entities whose canonical is in `name_candidates`/`speakers` ("knowable"). |
| `hedge_preservation` | | each gold hedged statement matched to a line (overlap ≥ 0.6); preserved when the line contains a modality marker for the language (`wahrscheinlich, vermutlich, voraussichtlich, geplant, erwartet, könnte, dürfte, laut, Schätzung, unbestätigt, nicht bestätigt` / `likely, probably, expected, planned, estimated, could, may, reportedly, unconfirmed, according to` / `ймовірно, очікується, планується, за словами, за оцінками, непідтверджено`) **or** its cited fact's `certainty` ≠ `fact`. |
| `attribution_rate` | | lines whose cited facts have `certainty ∈ {opinion, prediction, proposal, allegation, estimate}` that contain a capitalised token matching a speaker name, `name_candidate` or gold entity. (Will be low until Q4; measured from now.) |
| `date_resolution` | | Q3 wires it; in Q1 the function exists and returns `null` when the engine exposes no resolved dates. |
| `must_contain` / `must_not_contain` | | per string, present/absent over all lines + note title. |

`summarise()` adds all of the above, per meeting and aggregated; per-third recall and per-type recall breakdowns. The JSON report stays numbers and ids (the scorer never writes a line or a gold string into the report; failures of `must_*` are reported as the **index** of the string).

Tests (`tests/unit/test_notes_scoring.py`): one hand-built case per metric, including: a supported German sentence with a stemmed noun; a sentence introducing a new name → unsupported and invented; two near-identical bullets → redundancy; a hedged gold fact matched to a flat line → not preserved; the same with `certainty="prediction"` on the fact → preserved.

**verify:** `uv run --project services/note-service pytest tests/unit/test_notes_scoring.py -v`

### T6 — Optional judge column (eval only)

`--judge <backend>`: for each `framing|summary|bullet` line, one `provider.complete` call with schema `{"supported": bool, "problem": enum[none, new_claim, wrong_number, wrong_actor, stronger_than_said, other]}`, prompt = the line + the cited facts' `text` and `quote` (never the whole transcript), temperature 0. Report `judge_unsupported_rate` and the `problem` histogram, and — the number that decides whether a judge ever goes to production — `deterministic_vs_judge_disagreement`. Cost is logged through the same usage counters the harness already reports. No judge in the pipeline, the worker, or any service.

### T7 — Regression checklists

`scripts/eval/notes_assert.py` + `make eval-notes-assert CORPUS=…`: for each `<id>.assertions.json` beside a corpus file, run the pipeline arm and check the audit's checklist as data:

```json
{ "id": "r01_de_zeit_was_jetzt", "recording_type": "podcast_broadcast", "topics_min": 2,
  "speakers": {"SPEAKER_1": "Imre Balzer", "SPEAKER_2": "Fabian Reinbold"},
  "must_not_contain": ["November", "Teambesprechung", "Entscheidung", "Fraktionsvorsitzende", "Schmerz", "Schlesing", "Hinweis zum Transkript"],
  "must_contain_any": [["PKV", "privat"], ["Tankrabatt"], ["Rente mit 63"], ["Schwesig"], ["Söder"], ["3.000", "3000", "dreitausend"], ["Usmanow"], ["Fridman"], ["Lettland"]],
  "hedged_must_keep": [{"match": "Rente mit 63", "markers": ["wahrscheinlich", "voraussichtlich", "Prognose"]}],
  "dates": [{"text": "am Montag", "resolved": "2026-09-21"}],
  "every_line_cited": true }
```

Output: pass/fail per check, by index; exit 1 on any failure. The ZEIT transcript itself is placed by a person in the eval bucket under `eval/notes/v2/regressions/r01_de_zeit_was_jetzt.json` and locally under `scripts/eval/local/` (gitignored). The repo holds only the assertions file. `m06_de_news_podcast.json` gets its own assertions file so the check runs in CI on synthetic data.

Expected result in this sprint: **r01 fails** on most checks. That is the point — Q2–Q5 turn them green in order, and the file says which sprint owns which check (a `"sprint"` key per check is allowed and reported).

### T8 — Nightly job and the baseline report

`.github/workflows/nightly-notes.yml`, copied from `nightly-der.yml`: runner `mdx-eval`, `make dev-model`, `make eval-notes BACKEND=dev_mac ARM=pipeline CORPUS=<bucket path>`, same for `single_pass`, then `make eval-notes-assert`, then `scripts/eval/compare_notes.py` (new, mirrors `compare_der.py`) against committed `docs/eval/notes-baseline-pipeline.json`: fail when `unsupported_rate` rises by > 0.01, `invented_claims > 0`, `example_echo > 0`, or `key_fact_recall` drops by > 0.02. The baseline is updated only in a PR that carries the new report.

Run both arms once on `tests/fixtures/eval/notes` and on `eval/notes/v2` (whatever exists in the bucket by the end of the week) with the stack model; commit the two reports and `docs/eval/notes-baseline-2026-09.md`: one table, the §3 metrics, ours vs baseline, numbers only. That table is the exit criterion for Q1 and the "before" column for Q2–Q5.

## Security

No new data path. The judge (T6) receives fact texts and quotes of the run being evaluated — the same content the reduce step already sends to the same backend. Reports and assertion files never carry transcript text; the ZEIT transcript is never committed. `EXAMPLE_PHRASES` is derived from prompt text, so it cannot contain recording content by construction.

## Failure scenarios

| Case | Behaviour |
|---|---|
| Corpus path missing | harness exits 3 with the path; nightly marks the run failed, no comparison |
| Model unreachable mid-run | existing `ProviderError` handling; report marks the meeting `failed`, aggregate excludes it, exit 1 |
| Zero windows for a non-empty transcript | exit 2 (T1) |
| Judge backend unreachable | judge column `null`, run continues |

## Tests

| Test | Expected |
|---|---|
| harness shape → `turns_from_result` | n turns, names applied |
| zero-window run | exit 2 |
| gold validator on v1 files | no problems |
| gold validator on a file whose surface form is not in the transcript | one problem naming the entity index |
| `lines` ≡ `section.text` | equal per section |
| render snapshot before/after T3 | identical |
| example phrase in a fixture | fails |
| echoed example sentence | dropped, counted |
| prompts carry only this recording | passes for A then B |
| each scorer | hand-built case |
| compare_notes on a worse report | non-zero exit |

## Done when

1. `make eval-notes BACKEND=dev_mac ARM=pipeline` on `tests/fixtures/eval/notes` reports `windows_total > 0` for all eight fixtures and every metric in T5 has a non-null value.
2. `make eval-notes BACKEND=dev_mac ARM=single_pass` runs on the same corpus and writes its report.
3. `docs/eval/notes-baseline-2026-09.md` exists with both columns.
4. `test_prompts_carry_only_this_recording` and `test_an_echoed_example_never_reaches_the_note` pass; `docs/security/2026-09-22-november-sentence.md` exists.
5. `make eval-notes-assert` runs `m06`'s checklist and reports per-check results; `r01` runs when the bucket corpus is mounted.
6. `nightly-notes.yml` is green on a manual dispatch (`workflow_dispatch`).
7. `make lint && make lint-imports` pass; note-service unit suite passes.

## Report back

Files created/changed · unit test counts · the baseline table (numbers only) · which Inspect-first facts did not hold · how many `r01` checks pass today · open problems.

## Issue breakdown

| # | Title | Depends on |
|---|---|---|
| Q1-1 | eval: harness emits result-view shape; loud exit on zero windows | — |
| Q1-2 | eval: gold format v2, validator, fixtures m06–m08 | — |
| Q1-3 | engine: line-level provenance on `RenderedSection` / `DocumentResult`; keep `certainty` | — |
| Q1-4 | engine: prompts without content; `EXAMPLE_PHRASES`; echo guard; own-recording test; security note | Q1-3 |
| Q1-5 | eval: scorers + unit tests | Q1-2, Q1-3 |
| Q1-6 | eval: judge column | Q1-5 |
| Q1-7 | eval: assertions runner; r01 + m06 checklists | Q1-5 |
| Q1-8 | ci: nightly-notes workflow; compare script; baseline reports and table | Q1-1, Q1-5, Q1-7 |
