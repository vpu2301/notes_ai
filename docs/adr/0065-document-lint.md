# ADR-0065 — D1: a lint for the note's form

**Status:** Accepted · **Date:** 2026-09-27 · **Trigger:** the error taxonomy
(`docs/eval/error-taxonomy.md`), whose document-layer codes name "D1 lint" as their detector

## Context

The taxonomy's document layer (D-ORIENT, D-STRUCT, D-HEAD, D-SPEC, D-VOL, D-REF, D-LABEL, D-LANG,
D-FORM) had rules in render and in the amendment after r03, but nothing that reads a finished
note and says what is wrong with its form. The D1 work order and the "standard" it cites (§2
overview, §4 headings) are not in the repo. This lint is built from the taxonomy's definitions.

## Decisions

1. **`meeting_doc/lint.py` detects; it rewrites nothing.** Input is the rendered sections (or,
   in eval, the produced sections and lines). Output is findings of `(code, rule, section key,
   line number)` — never a line's text — so findings can be stored, counted and printed.
2. **It runs on every generation.** `stats.lint` holds counts by code and `stats.lint_rules` by
   rule. The metric `mdx_note_generation_lint_total{code, rule}` counts them. The eval scorer
   runs the same function (`lint_findings`, `lint_clean_rate`), and a checklist can cap
   findings per code (`"lint": {"D-STRUCT": 0}`).
3. **Rules** (rule → code):

   | Code | Rules |
   |---|---|
   | D-ORIENT | no overview; overview without a framing line; a bullet in the overview |
   | D-STRUCT | no headings over 10 min; fewer than one heading per 15 min; a headed section with fewer than 2 points; sections out of time order |
   | D-HEAD | generic heading (closed list, en/de/uk); all caps over more than one word; over 8 words or 60 characters; ends in ":" or "."; the same heading twice |
   | D-SPEC | a bullet naming, counting and dating nothing (`support.specificity`, dates by the Q3 resolver) |
   | D-VOL | under 8 words of note per minute of audio (from 5 min); over 50 (from 2 min) |
   | D-REF | a content line citing no fact |
   | D-LABEL | a diarizer label or default name anywhere; "Erzähler/in" outside the framing line |
   | D-LANG | first person or "we" in prose |
   | D-FORM | citation marks, fact ids or a field name in text; markdown residue; a table in the overview |

## Deviations and open points

- **Thresholds the taxonomy leaves open are provisional:** words per minute (8 to 50), one
  heading per 15 minutes, 8 words or 60 characters per heading. Set them from eval/notes/v2.
- **D-LANG is broader than F2's first-person rule.** F2 drops facts on it, so it is narrow. The
  lint only reports, so "we" and "wir" count.
- **Not covered:** D-RED is the scorer's `redundancy`; D-NEST needs gold parts; a wrong
  recording-type label (D-LABEL's "Vortrag") needs gold. A bare German ordinal day
  ("zum zweiundzwanzigsten") is not a date to the Q3 resolver, so such a bullet reads as
  unspecific.
- **No gate yet.** Findings are counted, not blocking. A nightly gate per code waits for the
  baseline on v2.

On the stored r03 runs of Gemma 3 4B the lint finds exactly `no_headings_long` and `volume_low`.
