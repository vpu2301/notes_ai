# ADR-0057 — One client document, and meetings that remember the last one

**Status:** Accepted · **Date:** 2026-09-20

## Context

Two problems, one sprint.

**External rendering had no shape of its own.** The shared page and the
PDF each walked the note's sections and rendered whatever was non-empty.
That was always wrong for the transcript — which the page tabbed away
with a heuristic rather than excluding — and it became a disclosure when
Sprint 34 gave every template a `user_notes` section. From that moment,
a shared note rendered the author's private in-meeting scratchpad
("ask about budget", "Tom is stalling") to the recipient, and the
recipient's PDF did the same. This was live in the repository.

**Meetings had no memory.** A weekly client call is one conversation held
in instalments, and the most useful line in instalment three is *"still
open from last week"*. `notes` knew only which dictation session or
transcription job a note came from; there was no edge between notes at
all.

## Decision

### 1. External surfaces render a client document, by allow-list

`domain/client_view.py` builds a `ClientDocument`, and **every** external
surface renders that and nothing else: the shared page, the shared PDF,
and the author's preview all call the same pure function, so what the
author checked and what the client received cannot differ.

* Sections are chosen **by role**, not by key. A key like `objections`
  means nothing outside a sales call; `decisions` means the same
  everywhere. `domain/meeting_doc/types.py` owns the key → role map.
* The roles that may appear are a fixed, ordered **allow-list**. A role
  nobody listed is internal by omission — the direction a mistake should
  fail in — so a template we have never seen cannot smuggle a section out
  by naming it something new.
* `user_notes` and `transcript` can never appear, in any family.
* A section that **is** a transcript is excluded whatever slot it sits
  in. This matters more than the key: until the generation engine lands,
  `from-transcript` drops the whole recording into the first prose
  section, usually `discussion`. The rule is "no transcript", not "no
  discussion" — dropping the section wholesale would gut every note
  people share today.
* A line prefixed `(internal)` — localised — is dropped, and the mark
  never renders anywhere, internal or external. The mark is stripped
  **before** the line's `item_key` is computed, so marking a line
  internal does not detach its evidence, its recipient responses or its
  correction history. That is what makes the toggle safe to use.
* Families with no client (1:1, interview debrief) produce **no**
  document at all and answer 409 `not_available_for_type`. Building one
  would be building a way to send a colleague's performance conversation,
  or a candidate's assessment, outside the workspace. Both families are
  also `private` by default.

The pre-share checklist warns; it never blocks. ADR-0051 removed the
lifecycle gates on sharing, and this is the author's judgement to make.

### 2. Series are joined on a hash, carry-over on structured items

`note_meetings` gains `series_key`, `series_source` and
`previous_note_id` (migration 0051). The key is a **hash**, never
content:

1. the calendar event's **iCalendar UID** when the capture started from
   one — every instance of a recurring event shares it, and it survives a
   renamed meeting, a moved slot and a changed guest list. A one-off
   event has a unique UID, so it never matches: the right outcome with no
   special case;
2. else the normalised **title plus the attendee set**, and only when
   there are attendees — "Weekly sync" with three clients is three
   series, and without the attendee half it would be one. Generic titles
   ("catch-up", "jour fixe") are refused outright;
3. else nothing.

Carry-over is a deterministic join on `note_action_items` (Sprint 20),
not retrieval and not a model. The previous meeting's open items are
restated as check items under "Still open from {date}", keeping the
**previous note's** `item_key` so the recipient's confirmation on that
meeting stays reachable. Items still open are **not** duplicated into the
new note's own action items.

### 3. The binding visibility rule

> A previous note is used only when the **author of the new note** may
> view it.

RLS scopes every query to the tenant, and a colleague's private 1:1 is
inside my tenant — so the tenant boundary is not the boundary here. Every
path into another note's content goes through `access.can_view` first,
and the candidate walk skips an unreadable note rather than giving up, so
one private note in the middle of a shared series does not blank out the
carry-over. Access taken away later stops the block resolving.

## Rejected

- **Subtracting from the note** ("render everything except X") for
  external surfaces. Every new section would be public until someone
  remembered to exclude it. The allow-list fails the other way.
- **Trusting section keys alone.** The transcript lives in `discussion`
  today; keys would have shipped the whole recording.
- **Dropping `discussion` from the client document**, which the sprint
  plan's section list implies. It would empty most notes people share
  today. Excluding transcript-*shaped* text achieves the actual goal.
- **Carrying items by copying them into the new note's action items.**
  They belong to the meeting where they were agreed; copying doubles
  every task in a long-running series and detaches the responses.
- **A series key from the title alone.** Two meetings called "Catch-up"
  are not a series.

## Consequences

- Recipients of existing links see less: the transcript and the
  scratchpad are gone, and sections are in a fixed reading order rather
  than template order. This is the intended correction of a disclosure.
- The author's own PDF is unchanged (`variant="full"`); the client PDF is
  `variant="client"`.
- `series_key` and `item_key` are hashes, and `note_carried_items` holds
  a completion quote only when the recording provides one — content,
  cascade-deleted, never logged.

## Status of the generation engine

Sprint 33 is **not in this repository**, so the parts of Sprint 36 that
consume generated facts are not built: type-specific extraction kinds,
judgement suggestions, `completion` facts (so `done_mentioned` is never
set by the system — only `done_marked`, by the author), the follow-up
draft, and the `audience` column on generated items. `types.py` already
declares the families, their kinds and their internal-by-nature lists, so
the engine has one table to read rather than a branch per type.


---

## Amendment — Sprint 36 completed (2026-09-20), now that the engine exists

The parts of Sprint 36 that needed Sprint 33's generation engine are built.
Four decisions, all of them narrowing what a model is allowed to do.

1. **A family's fact kinds are its own.** `schema.extract_schema()` is
   built per call from `types.py`: a sales call chooses between the kinds
   it might actually see, not the union of every kind in the product. The
   enum is the main lever on a small model's accuracy, and turning a kind
   off for a family whose precision is poor is deleting one entry in the
   table — configuration, not code. A fact whose kind this family does not
   have is dropped rather than filed somewhere arbitrary.

2. **A judgement is only ever offered.** `render.py` never writes a
   `choice` or `date` field's `field_specific_metadata`; a
   `judgement` fact is stored `placement='suggested'`, `audience='internal'`,
   with its quote, for a person to accept through the ordinary draft PUT.
   A machine that sets a deal stage or a hire recommendation has made a
   decision nobody asked it to make.

3. **A completion may only point at an item we already had.** The prompt
   receives the open carried items as a NUMBERED list and `refers_to` is
   an integer bounded by the schema, so the engine can reference a task
   but never invent one, and never name one in free text we would then
   have to match. Without a verified quote the item stays open, and the
   state is `done_mentioned` — distinct from a person's `done_marked`,
   because the distinction is who is claiming it.

4. **A commitment's side follows the NAME, not the kind.** A model that
   labels a task `commitment_ours` when the client took it on has guessed;
   the names are evidence. A side we cannot establish is `side_unknown`
   and renders in its own group — a task filed under the wrong side of a
   client note is worse than one filed under neither.

**Internal by kind**, not only by the author's mark: `note_generated_items.audience`
is set from `types.is_internal_kind`, and `client_view` drops those keys.
The author should not have to notice that an "objection" is not something
to send the person who raised it.

### A bug this pass found and fixed

Carry-over writes "Still open from…" into the action-items section at note
creation. To the writer that looked like author-written text — so the
engine would refuse to touch the section, and **would never write a task
into a series meeting again**: the two headline features of Sprints 34 and
36 silently cancelled each other out. `carry_over.split_block` now
separates the block from the rest; the block is preserved, and the
writer's ownership rule applies to what follows it. Caught by running the
handler end-to-end against the real schema, not by a unit test — and now
pinned by four.

### Still open

The follow-up draft (B-5: `note_followups`, the `note.followup` job,
routes and hand-off), type detection and the change-type rebind (B-2), the
de/uk prompt review (B-6), the template editor (B-7, P2), and the Sprint 36
client work on web, iOS and macOS.
