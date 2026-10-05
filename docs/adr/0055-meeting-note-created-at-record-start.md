# ADR-0055 — The meeting note is created at record start, not after transcription

**Status:** Accepted · **Date:** 2026-09-20

## Context

Until now a note did not exist until transcription had finished **and** a
client was still open to call `POST /v1/notes/from-transcript`. Two things
followed from that, both bad.

The first is that there was nowhere to type during a meeting. While
recording, the web page showed a title, a level meter and Stop; the Swift
capture views showed a title field. What the author notices in the room —
"this is the real objection", "ask about budget", "Tom hesitated here" — is
the highest-value signal there is about what actually mattered, and we threw
all of it away. The benchmark product's whole mechanic is built on keeping it.

The second is that the note depended on a client surviving the wait. Close
the laptop during transcription and the meeting stayed a transcription job
that nothing ever turned into a note.

## Decision

**One note, created early, filled later.**

1. `POST /v1/notes/meeting` creates the note as Record is pressed, with the
   template family the meeting type implies, the `user_notes` section empty,
   and `attendees` / `agenda` already filled from the calendar invite when
   there was one. It is **idempotent on `client_capture_id`**: a retry, a
   double tap and a second device resuming the same capture get one note.
2. `notes.source_asr_job_id` becomes **set-once-later** rather than
   set-at-create. The partial unique index from migration 0045 is unchanged
   and is still the single authority on "one note per transcription": both
   `POST /{id}/meeting/job` and `from-transcript` hit it, and the loser gets
   409 `already_assigned`.
3. **States live on a sidecar, not on `notes.status`.** ADR-0051 left a note
   with two statuses (draft until cancelled) on purpose, and "is the audio
   still uploading" is not a property of a document. `note_meetings`
   (migration 0049) holds `recording → uploading → transcribing →
   generating → ready`, with `no_audio` and `failed` as the two ways out.
4. **The author's text is an input, not a draft to polish.** It stays
   verbatim in `user_notes`. Nothing rewrites it, reorders it, summarises it
   or corrects it — the templates' synthesis prompt for that section says so
   in as many words. A line the recording cannot support is kept and marked,
   never quietly dropped.
5. **Line times are a sidecar too.** `note_user_line_times` maps
   `line_key → offset_ms` (first keystroke, relative to `started_at`).
   `NoteContent` is `extra="forbid"` and hash-chained (ADR-0020): typing
   rhythm is not part of the record. `line_key` is
   `action_items.item_key(normalise_text(line))` — a truncated sha256 — so
   the same line typed on two devices is one line, a whitespace edit keeps
   its timing, and nothing in the sidecar, in a metric or in a log is content.
6. **`from-transcript` is unchanged.** Uploads and older clients still make
   a note out of a finished job. Both routes end in the same content
   assembly and the same section rules.

## Rejected

- **Keeping the scratch text on the client until the note exists.** Lost on
  a crash, invisible on the second device — which is exactly the failure the
  sprint exists to remove.
- **A separate "scratch" entity merged into the note later.** Two documents
  to reconcile, two places to look, two things to get wrong at merge time.
- **Putting the states on `notes.status`.** Re-opens the lifecycle ADR-0051
  closed, and makes every consumer of a note branch on transport state.
- **Line times inside `NoteContent`.** Would put keystroke timing in the
  hash chain and force a schema change on a model whose whole value is that
  it is fixed.

## Consequences

- Two creation flows exist deliberately. They converge: `attach_transcript`
  and `from-transcript` both render the transcript with the same rules and
  drop it into the same prose section.
- A capture whose client never came back sits in `recording`/`uploading`
  forever, so a `meeting_state_sweeper` job (12 h, `MDX_MEETING_STALE_HOURS`)
  calls it `no_audio`. It never deletes anything: the note keeps what was
  typed, which is the part that cannot be recorded again.
- Attendee names and invite agenda lines are content. They are stored on
  `note_meetings.calendar_context`, never logged or audited (`pii_filter`),
  deleted with the note and included in a DSAR export. A raw invite
  description is read once for its agenda and discarded.
- **Not closed by this ADR:** the server still cannot chain transcription to
  generation on its own (debt D-1). Any client of the author, on any device,
  can now attach the transcript, which makes the gap much smaller, but a
  meeting whose author never opens any client again still waits.

## Status of the generation engine

The route contract includes `state = 'generating'` and this ADR describes it,
but the generation engine (extract / reduce / render over the transcript) is
Sprint 33 and is **not built in this repository yet**. Until it is,
`POST /v1/notes/{id}/transcript` fills the transcript section and goes
straight to `ready`. The state machine does not change shape when the engine
lands — that route gains an enqueue and stops one state earlier.


---

## Amendment — Sprint 35 (2026-09-20): linkage by `item_key`

Sprint 35 makes a generated line correctable without detaching it from
everything that hangs off it. Three decisions extend this ADR rather than
replace anything in it.

1. **A line is addressed by content hash, never by position.** Its
   `item_key` is `item_key(normalise_text(body))` over the line with its
   marker, owner prefix and due phrase stripped — the same hash the
   recipient loop has used for action items since Sprint 20. The rules now
   live in one place, `domain/lines.py`, because three modules had been
   splitting section text independently and a disagreement between them
   silently re-keys a line.

   The consequences are all intended: evidence and recipient responses
   survive reordering, a move to another section, and an owner or due-date
   edit; and when the author rewrites the *body*, the key changes and the
   line becomes theirs. `PATCH /v1/notes/{id}/items/by-key/{key}` refuses a
   change that would alter the key, rather than writing a version that
   quietly orphans the line's history.

   Rejected: inline markers in the text (they pollute Markdown export, the
   PDF and the markdown-lite parser) and positional anchors (they break on
   the first edit).

2. **A correction is logged without its content.** `note_item_corrections`
   holds the key, the kind, a closed-vocabulary reason and the flags the
   line carried — no text at all. The table feeds the weekly quality
   report and the eval gold set, and both must be readable by a role that
   may never see note content. The same rule applies to the audit
   payloads.

3. **The workspace glossary is opt-in, per term.** A correction *offers*
   to remember a spelling; only a yes writes a row. The list is visible in
   Workspace settings and every entry is deletable by whoever added it.
   A vocabulary that learned silently would, the first time it learned
   something wrong, misspell a customer's name in every note afterwards
   with nobody able to find out why.

   Terms are personal and business data: tenant-scoped, in the DSAR
   export, never in a log or an audit payload, and rendered in three
   clients — so control characters and bidi overrides are **refused**
   rather than stripped, and the term goes into a prompt as data inside
   the delimiters, never as instruction.

**Addressing deviation.** The sprint plan wrote
`PATCH /v1/notes/{id}/items/{item_key}`, but `PATCH /items/{item_id}` has
addressed items by row UUID since Sprint 20. The two cannot share a path
shape, so corrections took `/items/by-key/{item_key}`; `dismiss` and
`restore` keep the planned paths, whose trailing literal segment already
disambiguates them.

**Blocked on Sprint 33, and therefore NOT in this amendment:** the evidence
read model (`GET /v1/notes/{id}/evidence`), every flag, the author-vs-AI
marking rule, suggestions (`placement`, `POST …/add`) and "regenerate never
re-adds a dismissed key". The correction log's `flags_at_time`,
`prompt_version` and `model_id` columns and `dismissed_keys()` exist and are
written empty, waiting for it.
