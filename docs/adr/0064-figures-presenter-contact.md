# ADR-0064 — Figures, a presenter and a call to action, verified like facts

**Status:** Accepted · **Date:** 2026-09-26 · **Sprint:** F3 ("Figures, presenter, contact") ·
**Trigger:** the Pardo 65 GT walkthrough, where the note carried none of the eight specifications,
the presenter or the call to action

## Context

A product walkthrough is mostly numbers attached to named quantities, a person saying who they
are, and a request to get in touch. The engine had no kind for any of them, and `check_numbers`
read digits only — while since G0 a conversation's transcript keeps "eighteen and a half" as
words.

## Decisions

1. **Numbers are read as said** (`meeting_doc/numbers.py`): digits and number words in en/de/uk —
   cardinals to the millions, "point", "and a half", quarters, German compounds
   ("achtzehneinhalb", "zweitausendfünfhundert"), Ukrainian forms and "півтора".
   `check_numbers` accepts a number said in words, so `numbers_removed` can only fall.
2. **`figure` is a generic fact kind with a payload** (`name`, `value`, `unit`, `qualifier`),
   offered to every family. The value must be said (digits or words), the unit said (a
   written unit's spoken forms count: "ft" ↔ "feet"), the name share a word with the quote, the
   qualifier be on a closed per-language list and in the quote — else cleared. A figure failing
   value or unit is dropped (`figures_dropped_value|unit`), never softened.
3. **A table is a rendering decision.** Figures sit in the topic that cites them — a
   `| Quantity | Value |` table from three on, "Name: value" bullets below — else in the engine's
   `specifications` section (Specifications / Technische Daten / Характеристики). Rows are Q5
   line rows of kind `figure` with the payload in the new `payload` column (migration 0065);
   the head row cites nothing and has no row. The same name and value merge (a second source);
   the same name with another value is two rows, both flagged `figure_conflict`. A model bullet
   that only restates figures is not written; a topic's figures count towards it staying a topic.
4. **A presenter is an `introduction` fact**, verified word by word (the name whole; a role,
   organisation or qualifier word not in the quote clears that field). For the broadcast family
   the first self-introduction is one line under the framing sentence — "Presenter: Mitchell,
   broker with Springbrook Marine Group (Pardo dealer for the Great Lakes)" — and anybody else
   introduced is "Introduced: …". The extractor is told which lines of the first two windows hold
   an introduction (an engine cue list, plus asr-service's `name_suggestions` quotes, which now
   carry `role_text` verbatim). An introduced name joins the names a line may use.
5. **A call to action is a `next_step`** (broadcast family only). When its quote addresses the
   listener it is the Contact section, key `call_to_action`; otherwise it becomes a key point.
6. **`presentation_demo`** is a recording type (classifier enum, prompt clause, 0065 CHECK on
   `meeting_type_detected`) mapped to the broadcast family, which now offers `introduction` and
   `next_step`.

## Deviations from the work order

- **`introduction` is offered to the broadcast family only**, not to meetings. A meeting's
  introductions already reach speaker names through asr-service's suggestions (Q4), and a
  larger kind enum costs a small model precision.
- **The Contact section's key is `call_to_action`**, not `contact`: templates already use the
  section id `contact` for the attendee block (`roles._BY_ID`).
- **Figures render the value as digits** ("eighteen and a half" → 18.5), qualifier and unit as
  said; no unit is converted or abbreviated.
- **`merge_facts` now copies every field** (`dataclasses.replace`) — it rebuilt facts field by
  field and would have dropped F2's `copied` and F3's payloads — and never folds two figures
  with different payloads.
- The client version's allow-list gains `specifications` (a meeting's budget table is for the
  client too); a broadcast has no client version.
- `r02`'s checklist holds the two figures this work order states (66 ft length overall; just
  under 300 gallons of water) with `figures_min = 2`; the other six need the annotator and the
  bucket transcript. The synthetic twin `m11_en_boat_walkthrough` carries all eight kinds of
  check.

## Consequences

- A walkthrough's note leads with who presented and carries its specifications with a source per
  cell; a meeting with budget numbers gets the same verified figures, and no presenter or
  Contact section.
- Gates (`notes_scoring.f3_gates`): figure value accuracy 1.0, recall ≥ 0.85, qualifier
  preservation 1.0, presenter ≥ 0.9 — on files whose gold has them.

`PROMPT_VERSION` 2026-10-14.
