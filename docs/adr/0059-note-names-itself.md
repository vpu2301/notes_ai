# ADR-0059 — A meeting note names itself

**Status:** Accepted · **Date:** 2026-09-22

## Context

A recording opens its note with a placeholder — the template name and the
date on the server, "Meeting <date>" on the Mac and iPhone — because at that
moment nothing has been heard. The placeholder then stays forever, and a
notes list of dates says nothing about what each meeting was.

Nothing is transcribed while a meeting runs: the audio is uploaded at Stop
and the transcript arrives once, whole, at `POST /v1/notes/{id}/transcript`
(or `from-transcript`). There is no "first 150 words" moment to act on, and
the one place that already reads the finished transcript with a model is
the `note.generate` job (ADR-0058).

## Decision

1. **Where a title came from is on the row** (migration 0057):
   `notes.title_source` is `default` (a placeholder the server made),
   `ai` (named by the job), `user` (typed, or taken from the person's
   calendar event) or NULL (a note older than the column). The job only
   ever replaces `default`. Older notes are never renamed automatically.
2. **A rename is recorded by the statement that stores it.**
   `append_version` flips the source to `user` whenever the title changes
   and the caller did not say otherwise. Any client, any device and any
   future route is covered without a client flag, and the engine's own
   writes, which carry the title through unchanged, do not trip it.
3. **The job names the note first**, before the long document pass: one
   short call to the same provider, in the spoken language, over excerpts
   spread across the whole recording (so the title is the meeting's main
   subject, not its first sentence). Fewer than 12 real words, or a model
   answer of "no topic", keeps the placeholder.
4. **Checked twice, written once.** The source is read before the model is
   asked (a retried job or a regenerate costs no call) and again under the
   note's row lock just before the write, so a rename made while the model
   was answering wins. The write sets `ai`; nothing renames the note
   again. There is no second pass at the end of the meeting: the
   transcript is already whole when the first pass runs.
5. **Never at the note's expense.** Every failure in the step is logged and
   swallowed; the document is written as before. The step follows the
   workspace's AI settings like the rest of the job: generation turned off
   or the budget spent means no title either.
6. **Clients send no placeholder.** The Mac and iPhone strip their own
   "Meeting <date>" before `from-transcript`, so a fallback note is still
   eligible, and they copy the server's title into their local recents
   when the note reloads.

## Consequences

- The title appears when a client next reloads the note, which today is
  when the generation finishes.
- A future "Generate title" action for older notes is the same
  `note_title.suggest` + `apply`, called on request with NULL treated as
  `default`.
