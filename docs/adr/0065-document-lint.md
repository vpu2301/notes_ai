# ADR-0065 — D1: no note below the document standard is written

**Status:** Accepted · **Date:** 2026-09-27 · **Implements:** Sprint D1 ("The document linter")
against `docs/eval/document-standard.md`, with the codes of `docs/eval/error-taxonomy.md`

## Decisions

1. **One linter, two callers.** `meeting_doc/doclint.enforce(document)` runs in the worker
   between `pipeline.run` and `writer.apply` (`jobs/generate_note.py`), and in the eval harness on
   every output (`scripts/eval/notes_eval.run_pipeline`). The scorer imports the same module.
   `pipeline.run` no longer lints: the pipeline's tests see the document the model produced; the
   writer sees the one the standard allows.
2. **Rules are data.** `doclint.RULES` maps each rule of the work order (`sections.count`,
   `heading.form`, `line.subject`, `orient.p1`, …) to a taxonomy code and says whether a D2
   regeneration can fix it. Severity is the code's (S1/S2 hard, S3 soft). A finding is
   `(rule, code, severity, section key, line index, detail)`; `detail` is a closed word, never
   text.
3. **Order of work:** check → hard findings with a hookable rule go to D2's `regenerate` once →
   deterministic repairs and fallbacks → check again. What is still found is `unresolved`.
   Stats: `stats.lint = {findings_by_code, findings_by_rule, repaired_by_code, regenerated,
   unresolved, unresolved_rules, unresolved_hard}`. Metric
   `mdx_note_generation_lint_total{code, outcome=found|repaired|regenerated|unresolved|
   unresolved_note|error}`; alert `NoteGenerationLintUnresolved` when unresolved S1/S2 notes
   exceed 10 % of complete generations over an hour.
4. **Repairs** (in order):
   - text: strip glyphs and ids (`line.glyph`), add the Q4 certainty marker (`line.certainty`);
   - lines: a line breaking a line rule is not rendered and its fact stays evidence
     (`line.cited`, `line.subject`, `line.person` after F2's mechanical fix, `line.language`,
     `line.copy`, `line.descriptive`, `line.specific`); sub-points go with their parent, past
     three or restating it are cut;
   - orientation: map the type word, rebuild paragraph 1 by code from the verified roles
     (`brief.orientation`, written by the pipeline), take the composed rung below three
     sentences, trim past six or 140 words, compose the block when it is missing;
   - headings: strip punctuation, recase all caps, cut to 8 words past 60 characters; a generic
     heading, one naming what its section does not say, or one restating the title takes the
     fallback heading (the section's name and first time); a heading saying what the one before
     it says merges the two sections;
   - sections: order by first cited time; one point joins its neighbour; past six split at the
     largest gap; too many merge where headings share ≥ 40 % or spans fit in 90 s; too few fall
     back to chapters (amendment §2.6);
   - redundancy: the later duplicate goes, or the earlier when the later is more specific;
   - volume: below 8·D render facts that meet the line rules, by time, into the section whose
     span holds them; above 18·D drop the least specific points, never below two per section.
5. **Titles (§1)** are constraints on `note_title`: 30–80 characters, one colon, no repeated
   phrase, not a placeholder shape. A failing suggestion is not applied (reason `lint`).
6. **`descriptive` gains evaluations** of a person or thing with no claim after them
   ("Alex Karp hatte einen ungewöhnlichen Lebenslauf"): no digits, no date, an evaluative
   adjective, and no reason or relative clause following.
7. **Eval gates** (`notes_scoring.d1_gates`): no unresolved S1; unresolved S2 in ≤ 2 % of notes;
   volume and section bands met on ≥ 90 %; no rendered line with a label or pronoun subject;
   none with specificity 0.

## Choices the work order leaves open

- **D2 is not merged.** The worker passes no hook; `regenerated` is 0 and fallbacks apply
  directly. The hook's shape is `regenerate(requests, sections) -> sections | None`.
- **D is transcribed speech minus exclusions.** The section count is judged from 5 minutes of
  speech, with the standard's own tolerance (target ± 2, never below 3).
- **An orientation sentence and a section line are never duplicates.** §2 has paragraph 2 name
  the most specific facts, which the sections carry too. Redundancy is measured within the
  orientation and among section lines.
- **Names in German headings and titles** are runs of capitalised words, acronyms and known
  names (every German noun is capitalised). A run like "Gast Felix Holtermann" counts as
  supported when all but its first word are.
- **"Es gibt …" / "It is …"** are expletives, not pronoun subjects.
- **Another language** means its stop words are at least twice as present as the note's.
- **Recasing German** capitalises every word but the function words. A word stays upper case
  only when the facts spell it so.
- **Not checked:** sentence case (undecidable for German nouns), tense.
- **`orient.p1` "every proper noun verified"** reads names against facts, verified speakers and
  guests; "Erzähler/in" needs a narrator entry in the roles.

## Consequences

- A short or unsupported title now keeps the placeholder: "Q4 Product Roadmap" is under 30
  characters. The prompt asks for 30–80.
- Our own code-composed first paragraph is under 25 words when no subject or themes were
  verified. It stays unresolved (`orient.p1 length`) until D2 writes it.
- Tests: `services/note-service/tests/unit/test_meeting_doc_doclint.py`; fixtures of r03 note 1,
  note 2 and the comparison note's shape in `tests/fixtures/meeting_doc/doclint/`.
