# ADR-0063 — Every line is a statement; a quote is evidence

**Status:** Accepted · **Date:** 2026-09-26 · **Sprint:** F2 ("Statements, not quotes") ·
**Trigger:** the Pardo 65 GT note, whose bullets were transcript sentences ("This boat is
incredible.", "again this is a little bit of a crowded boat right now…") with an evidence mark

## Context

`verify.is_copied` existed but applied only to decisions, and a copied decision was downgraded
to a key point and rendered anyway. "Skip small talk" was a prompt instruction nothing checked.
A small model that copies the transcript into `text` produced a note that was a transcript with
bullets.

## Decisions

1. **A copy is evidence, not a statement.** `is_copied` applies to every kind
   (`VerifiedFact.copied`, flag `copied`). A copied fact stays a citable fact — a summary
   sentence or topic bullet may cite it and its quote is shown — but render never writes its
   text as a line (fact sections, key dates, the untopicked list, salient bullets). Its row is
   stored with `placement = 'evidence'` (migration 0064) whether or not a line cites it, so the
   evidence popover can resolve every citation; the Detailed view never shows it.
2. **Restate on demand, per window, once.** When a window's verified facts include a copy
   (tuned from the work order's 40 %, see below), the window is extracted again with `RESTATE_SUFFIX` and no more
   facts than the first answer had. A restated fact that cites the same line and is not a copy
   replaces the copy; everything else stays. `mdx_note_generation_restate_total{outcome}`.
3. **Information is checked in code** (`support.carries_information`), on facts before they are
   stored and on every model-written line (gate reason `no_information`).
4. **Third person is enforced by pattern.** A leading "So," / "Again," / "Also," is dropped
   mechanically; a statement still in the speaker's voice (`I`, `We`, `You`, `Let's`, `Ich`,
   `Wir`, `Я`, `Ми` at the start; `I'll`, `we'll`, `you guys` anywhere) is `first_person`:
   evidence only. Tasks keep their wording ("We should update the deck" is an action).
5. **Sub-points.** `TopicBullet.children` (≤ 3, one level, each citing a fact). A child that
   cites only its parent's facts with Jaccard ≥ 0.6 to it is the parent again and is dropped.
   Rendered as `  - child`; stored as `topic_bullet` rows with `parent_key`; a parent already
   said takes its children with it.
6. **The evidence mark is an affordance.** No citation glyph is ever written into section
   text; the web draws ❝ with CSS and makes chips and the toggle unselectable, so copying a
   note never carries them along (the pasted note's ❝ came from a text selection).

## Deviations from the work order

- **The four-token floor is narrower than written.** Decision 3 said any line under four
  content tokens is `no_information` unless it is an action or a decision. Applied as written it
  dropped real short statements the suite relies on ("Das ist nicht verhandelbar", "Ticket
  prices were discussed") — recall the work order's own gate protects. Shipped: a line is
  `no_information` when nothing in it informs, or when it is short **and** judges (an
  evaluative word: "This boat is incredible."). A number, a name or a date always informs.
- **`first_person` facts are evidence, not deleted.** T3 says dropped facts are not stored;
  decision 4 says a first-person line is kept as evidence. Shipped: `no_information` facts are
  not stored; `first_person` facts are stored as evidence, like copies.
- **Copies are also caught in model-written lines.** A topic bullet, summary sentence or
  framing line that copies the quote of a fact it cites is refused by the gate (`copied`), and
  render drops a bullet that copies a cited quote.
- **Restate on any copy, not above 40 %** (tuned after the first eval, as the work order
  says to when recall drops). The 2026-09-26 run on Gemma 3 4B
  (`docs/eval/notes-pipeline-2026-09-26-dev_mac-f2-as-built.json`) fell from 0.61 to 0.39
  key-fact recall: two meetings lost their only window to invalid JSON under load, and m04,
  m07 and m08 lost facts that were copies in windows below the 40 % bar — "Candidate B was
  the strongest on the system design round" is a copy and was the gold fact. With any copy
  asking once, m04's copies came back restated. `is_copied` also checks each sentence of a
  multi-sentence quote, as the eval's scorer does.
- **Lexical recall under-counts a restatement.** The scorer matches gold facts by shared
  content words (≥ 0.6); "Candidate A experienced difficulty with concurrency questions"
  does not match "Candidate A struggled with the concurrency question". F2 trades verbatim
  lines for restated ones, so the recall gate measures part of the trade itself.
- `NoteGenerationUnsupportedLines` now counts the support outcomes only
  (`unsupported|number|name|example`); the F2 outcomes have their own alert,
  `NoteGenerationCopiedFacts`.

## Consequences

- A note can get shorter: a meeting of small talk writes nothing ("Nothing worth writing was
  found"), and a model that copies whatever it is told leaves only what summaries and topics
  say about the copies. Measured against the pre-F2 recall by `notes_eval.py` (`f2_gates`).
- The blind readability round is on topic bullets only (`notes_pairs.py build --section
  topics`); it needs human raters and is not run by CI.

`PROMPT_VERSION` 2026-10-13. Runbook: `docs/runbooks/notes.md#copied-facts`.
