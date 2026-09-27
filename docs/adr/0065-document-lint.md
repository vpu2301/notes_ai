# ADR-0065 — D1: the document standard, linted before the write

**Status:** Accepted · **Date:** 2026-09-27 · **Implements:** `docs/eval/document-standard.md`
(Sprint D1) with the codes of `docs/eval/error-taxonomy.md`

## Context

The document standard states what a generated note must look like, with numbers: title
length, two orientation paragraphs of set lengths, a section count from the recording's length,
heading and bullet lengths, one level of at most three sub-bullets, 8·D to 18·D words, under 5 %
redundancy, and a blind rubric with a release gate. It names `meeting_doc/doclint.py` as the
enforcer "before a document is written".

## Decisions

1. **`doclint.repair` makes only the mechanical changes.** A line that cites no fact is not
   written (§7), and a heading loses trailing ":" "." "!" (§4). Code never rewords a model's line
   or a person's words, so every other departure is reported, not fixed.
2. **`doclint.lint` reports everything else** as `(code, rule, section key, line)`, never text.
   47 rules across §1–§7, each mapped to a taxonomy code; most are D-codes, plus F-INV (an
   unsupported name in a title or heading), F-SUBJ, F-COPY and F-DESC for bullets. The rule
   table is `doclint.RULES`.
3. **It runs on every generation**, after render and before the write: `stats.lint`,
   `stats.lint_rules`, `stats.lint_repairs`, and `mdx_note_generation_lint_total{code, rule}`.
   Findings never block a note. The standard's release gate is the blind rubric (§8), and
   nightly gates per code wait for a v2 baseline.
4. **The eval runs the same function** (`notes_scoring.lint_produced`): `lint_findings`,
   `lint_clean_rate`, and the rubric's Q3 and Q7 read by code. A checklist can cap findings per
   code.
5. **Titles (§1) are held in `note_title.py`.** The prompt asks for 30–80 characters naming the
   subject and angle. An answer is cut at a word above 80 characters, and one with a second
   colon or a placeholder shape is refused. `PROMPT_VERSION` 2026-10-21.
6. **The rubric (§8)** is `notes_pairs.py rubric-build` / `rubric-score`. It is per note, blind
   across arms. Each page lists five random lines for Q4 and the word band for Q7. A note's score
   is the median of its raters, and the gate is mean ≥ 13/16, Q4 = 2 on ≥ 95 % of notes and no
   note with Q1 = 0.

## Choices the standard leaves open

- **D is transcribed speech:** merged turn spans minus exclusions, not wall time.
- **Section count** (`max(3, min(8, round(D / 4)))`) is judged from 5 minutes of speech, with
  the standard's own tolerance ("a 30-minute podcast has 6–8 sections"): too few below
  target − 2, never below 3. Under 5 minutes Q3's "too little to head" stands.
- **Paragraph 2's sentences** are its summary lines; a full-stop count would split at "11.".
- **Names in titles and headings** are runs of two or more capitalised words, acronyms and
  known names. German capitalises every noun, so a single capital proves nothing. A name is
  supported when every word appears in a fact's text or quote.
- **"Restates the title"** means every heading word is in the title. **Two headings sharing
  > 60 %** is measured over the smaller heading's words.
- **D-LANG is broader than F2's first-person rule** ("we", "wir", "ми"): F2 drops facts on its
  rule, and the lint only reports.
- **Not checked by the lint:** sentence case, since German nouns make it undecidable. Also the
  certainty marker, which the client's chip can carry instead. And tense consistency.

## Consequences

On the stored r03 Gemma 3 4B run the lint reports what the standard's own scoring of that note
says is wrong: a short first paragraph, no second paragraph, too few sections, too little text.
On the synthetic fixtures run through the scripted stand-in, it reports that stand-in's copies,
"Part 1" headings and two-sentence summaries. The engine's own gap it shows: with no verified
subject or themes, the code-composed first paragraph is under 25 words.
