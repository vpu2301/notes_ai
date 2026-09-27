# ADR-0066 — D2: composition to the document standard

**Status:** Accepted · **Date:** 2026-09-27 · **Implements:** Sprint D2 · **Supersedes:** the
amendment's A-10 (overview ladders), A-12 (two-stage topics over 40 facts), A-13 (specificity in
selection), A-14 (phase headings) and F2 T4 (sub-points) — implemented here once.

## Decisions

1. **Blocks, not one shot.** `compose.blocks(facts, D, topic_titles)` cuts the merged facts into
   `round(D/4)` time-contiguous blocks within [3, 8] (fewer when there are not four facts per
   block), at the largest gaps in time and where the extractor reported a new topic. One reduce
   call per block (`schema.BLOCK_SCHEMA`: heading, 2–6 bullets, up to three children), then one
   call over the headings for merges of neighbours, applied only while the section band holds.
   A call that fails is retried once; a block that still has fewer than two bullets is written
   as its chapter.
2. **Volume is budgeted first.** `compose.VolumeBudget(D)`: 12·D words; the block prompt asks
   for its share of bullets; selection keeps the most specific within it, in time order.
3. **Subjects are fields.** `Fact.subject` is verified by the owner rule over the window and is
   never a speaker label. A text that still opens with a pronoun is evidence (`subject_unresolved`).
   Render never substitutes a subject.
4. **Narrators report.** In a recording with a narrator or host, a third-person statement by that
   voice is attributed to its verified subject, never to the voice. Q4's default (an opinion is
   its speaker's) holds only when the quote is in the first person. A default speaker name is
   never a holder.
5. **Roles are a table.** `roles_table.build` gives each label its share, turns, first-person
   share, introduction and role. The orientation, presenter and guest lines, and attribution read
   it. A name that never spoke is a subject, never a guest.
6. **Cues settle lecture versus podcast** (`classify.type_cues`); a tie keeps the classifier; a
   type the user set is never changed.
7. **Orientation ladders.** Paragraph 1 comes from the table, type word, show jingle, subject and
   themes. Paragraph 2: model with the block headings → strict with the top fact of each block →
   code-composed prose.

## Choices the work order leaves open

- **The roles table takes the family** as well as the type: a walkthrough with no type in a
  broadcast family still has its presenter.
- **A heading's names** are checked with the linter's German-aware rule (runs, acronyms, known
  names), against the block's facts. Fallback headings use verified names only: the recording's
  frequent capitalised words (German nouns) are not names.
- **Quote children** are a new line kind `quote`, stored as `topic_bullet` rows (no migration),
  and exempt from the prose line rules.
- **D1's hook** is implemented for `line.subject` (re-extraction with "name every subject").
  Section count and orientation are regenerated inside the pipeline by the ladders and the
  chapter fallback, so the hook returns nothing for them.
- **Removed:** the one-shot topics call, A-12's two-stage rule, topic-overlap merging (blocks
  cannot overlap) and the amendment's standing rule (subsumed by the roles table).
- **Kept:** Q4's salient append — an uncited fact with a number, a date or a holder joins the
  block nearest in time.
- **Ukrainian podcast word:** "Епізод подкасту".

## Not measured here

Acceptance 2 needs `eval/notes/v2`; the blind rubric needs raters. `PROMPT_VERSION` 2026-10-22.
