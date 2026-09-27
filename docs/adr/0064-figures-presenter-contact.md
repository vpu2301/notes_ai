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

## After the first run on the stack model (Gemma 3 4B, 2026-09-26)

The engine as first built wrote no figure, presenter or Contact line on `m11` or on the Pardo
recording. What the small model does, and what now handles it — every step keeps "the model
proposes, code verifies":

- **It leaves optional fields empty.** A figure or introduction without its fields gets one
  follow-up call whose schema REQUIRES them (one line per call, ≤ 16 per window — asked about a
  dozen lines at once it answers the first few). A call to action no fact states gets one call
  for a single third-person sentence, verified like any fact.
- **It files numbers as key points and stops early.** A fact whose words carry a number, and a
  line with a number no fact covers, are asked about as figures; code picks the line, the model
  names the quantity, verification decides. A verified figure replaces the key point it came
  from.
- **It quotes the number words only, or the whole line with its header.** Name and qualifier
  are checked against the spoken line (and the same speaker's previous line for the name — "the
  water tank holds / just under 300 gallons"); the qualifier must sit directly before its own
  value, and when the model gives none, code reads a closed-list qualifier said right there. The
  line header ("[8] Speaker 1 (00:33):") is stripped first — it names the speaker on every line
  and would vouch for any introduction. A self-introduction is checked with the same speaker's
  next sentence ("We are the … dealer for all of the Great Lakes"), and keeps the transcript's
  casing.
- **It calls names and designations figures.** "Pardo 65 GT", "IPS 1200s", "a 52 gt" and a bare
  year are not quantities; a unit is not a quantity's name; a product in a welcome is not an
  introduction (an introduction cue is required).
- **The one-voice rule called a short walkthrough a voice memo.** The classifier's
  `presentation_demo` now survives it (Q3's podcast rule is unchanged).
- **F2's restate replaced figures** whose text copied the line; payload facts are exempt.

Result on the stack model, one run each (model output varies run to run):
`docs/eval/i3-stack-model-2026-09-26.md`.

## Amendment after regression case r03 (2026-09-26/27)

r03 is a 11-minute German podcast on Palantir with a trailer at the start. The note called
the trailer's voice the presenter, made a "Technische Daten" table from "Zwanzig Jahre" and
"Eine Software", wrote scenery as key points, and rendered no headings. Fourteen issues,
A-1 to A-14, changed these rules:

- **A-1 · presenter gating.** An introduction is a `presenter` only when the voice is the
  dominant speaker (≥ 15 % of speech, ≥ 3 turns) and no broadcast cue ("präsentiert von",
  "jetzt im Kino", …) follows within 20 s. Any other voice with ≥ 3 turns is a `guest`
  ("Gast: Felix Holtermann, Büroleiter beim Handelsblatt"). Anybody else is a `clip` and gets
  no line.
- **A-2 · adverts are exclusions.** A run of turns with an advert cue is cut before windowing
  as `Exclusion(reason="advertisement")`, then windows are rebuilt (`stats.adverts_cut`).
- **A-3 · figure validity.** An article is not the number one ("Eine Software"). A value of
  one needs an explicit "one"/"eins". A unit word, a digit or a number word is not a name.
  A bare year and a product designation are not quantities. With no unit, a quantity noun
  must be said.
- **A-4 · tables only where a table belongs.** Figures form a block only in a
  `presentation_demo` or `lecture_webinar`, or when three or more give two measured
  quantities. Anywhere else they stay rows under the statements that say them.
- **A-7 · micro-turns.** A turn of ≤ 3 words and ≤ 1.5 s between two turns of one speaker joins
  them (`stats.microturns_merged`). The diarizer's output is untouched.
- **A-8 · the recording's own names.** A capitalised word said ≥ 3 times is a name the
  recording spells. A once-said word one letter away is corrected to it ("Carp" → "Karp").
- **A-6 · chapters.** A recording over 10 minutes whose topics fail is chaptered by time.
  Spans are one window and at most 3 minutes, of ≥ 3 facts. Each is headed "mm:ss — Name" by
  the name that span says most and that more than half the spans do not say
  (`stats.topics_fallback = "chapters"`).
- **A-10 · the overview is prose.** Paragraph 1 is composed by code: type, subject (or the
  model's framing when the gate passes it), speakers, guest and themes. Presenter and guest
  lines belong to paragraph 1. Paragraph 2 comes from a ladder: the model's summary, then a
  strict retry with a skeleton of fact ids, then composed prose with connectives
  (`stats.summary_ladder`). The key-point list is gone. A single topic keeps its heading.
- **A-11 · the support gate per language.** A claim word also counts as supported when it
  shares six letters in a row with an evidence word. Thresholds are en 0.5, de 0.4, uk 0.4.
- **A-12 · two-stage topics.** Over 40 facts, topics are asked block by block (≤ 8 blocks of
  ≥ 4 facts). Neighbouring same headings (Jaccard ≥ 0.6) merge in code. A failure is
  recorded as `stats.topics_failure`.
- **A-5, A-13 · scenery and specificity** are F2 rules; see ADR-0063.
- **A-14 · phase headings.** The block prompt asks for a noun phrase naming the part of the
  story.

### Deviations from the amendment

- **Overview wording has no colons.** The amendment's example reads "Sprecher: Erzähler; Gast:
  …; Themen: …". A "Label: text" line is what `client_view.looks_like_transcript` and the
  shared page take for a transcript turn, so paragraph 1 reads "Es sprechen Erzähler/in und
  als Gast Felix Holtermann (Handelsblatt). Themen sind …". Connectives use a dash
  ("Zunächst — …") so German word order is untouched.
- **`unit_lost` replaces a unit fill.** A unit said after the value but missing from the
  figure drops it (`figures_dropped_unit_lost`); code does not fill the unit in.
- **Headings merge in code**, not with a third model call over the headings.
- **"Tiers" is not flagged `(?)`.** A-8 corrects only within one letter; a word it cannot
  place stays as said. The Corrections panel remains the way to fix it.
- **Chapters are also split by time**, not only by window: one 4B window can hold ten minutes.
- **"Erzähler/in" needs one voice with ≥ 60 % of the talk.** Two unnamed voices sharing it are
  not called a narrator. "Speaker 2" and "UNKNOWN" are never listed as speakers.
- **F2 wins over "always two paragraphs".** When every fact is a copy, no statement is left
  for paragraph 2 and it is not written: a transcript sentence is never a line. On r03 with
  Gemma 3 4B that happens (`docs/eval/r03-amendment-2026-09-27.md`). Open for a product decision.
- **The thresholds are provisional.** They are the amendment's expected values. They have not
  been calibrated: that needs a judge stronger than the model under test on
  `eval/notes/v2`. `scripts/eval/support_calibration.py` reads `notes_eval --judge-lines`.
- **The r03 checklist's `sprint`** is a map from check to "F3-amendment", as the checker
  reads it. It also forbids the five claims the other product invented (§5).
- The workspace hint for r03 was cleaned by hand (Moderator, Gregor Gysi and five role labels
  soft-deleted). The bucket upload of r03 is not done from here.

## Consequences

- A walkthrough's note leads with who presented and carries its specifications with a source per
  cell; a meeting with budget numbers gets the same verified figures, and no presenter or
  Contact section.
- Gates (`notes_scoring.f3_gates`): figure value accuracy 1.0, recall ≥ 0.85, qualifier
  preservation 1.0, presenter ≥ 0.9 — on files whose gold has them.

`PROMPT_VERSION` 2026-10-14; after the r03 amendment 2026-10-20.
