# ADR-0051 — A note is a living document: the finalize lifecycle is retired

**Status:** Accepted · **Date:** 2026-09-17

## Context

Sprint 08 gave a note a `draft → finalized → amended` lifecycle with
validation at finalize, a one-hour revert window, a versioned amend
route, a DRAFT watermark on the PDF and (Sprints 19/23) a gate that
kept drafts from being shared unless the sender acknowledged it or the
workspace allowed it. In a horizontal notes product none of that maps
to what people do: a meeting note is edited for days, shared while it
is still moving, and never "signed". The extra state produced three
menu entries, two confirm dialogs, a policy switch and a 409 code that
users had to learn, and every new surface (items, shared page, PDF)
had to branch on it.

## Decision

1. **Two statuses.** A note is `draft` until it is `cancelled`. The
   `NoteStatus` enum keeps `finalized` / `amended` so history decodes,
   but no code path produces them. Migration `0042` moves every
   frozen row back to `draft`; `finalized_at` is kept as history, so
   the 0009 CHECK that tied it to the status is dropped.
2. **Removed, not hidden:** `POST /notes/{id}/finalize`,
   `/revert-to-draft`, `/amend`, `domain/finalize_validator.py`, the
   `FinalizeProblem` contract, audit kinds `note.finalized`,
   `note.completed`, `note.reverted`, `note.amended`,
   `note.field.extracted` (documented as retired), the draft
   acknowledgement on recipient links, the `require_finalized` policy
   key (stored JSON with the key still loads: the policy model now
   ignores unknown keys), `is_draft` on the shared page and the
   watermark-by-status rule on the PDF (`?variant=draft` remains as an
   explicit choice). The web, iOS and macOS clients lose the menu
   entries, dialogs, badges and gates.
3. **Action items derive lazily.** They were materialised at finalize;
   now `action_items.ensure_items` builds them the first time a
   version is read (author items view, shared page). A version's
   content is immutable, so one pass per version is enough.
4. **Notification categories `note.finalized` / `note.amended` keep
   their consumer** (catalog, renderer, preferences) so rows already
   in the feed still render. The producers are gone.

## Consequences

- Sharing has no gate on note state; the recipient's "what changed"
  strip (Sprint 23) is what tells them the note moved.
- The `is_amendment` / `amendment_*` columns on `note_versions` are
  history only; the chain reconciler still verifies the chain, and
  every new version is an ordinary autosave.
- The dictation-service "finalize" (closing an audio session) and the
  `dictation.finalize` permission are unrelated and unchanged.
