# ADR-0071 — Per-note roles, workspace-visibility grants, guest memberships, the transcript rule

**Status:** Accepted (dev/staging). · **Date:** 2026-10-13 · **Implements:** Sprint W3
(workspaces & collaboration track) · **Related:** ADR-0069 (workspace = tenant), ADR-0070
(invitations), concept decisions 5–8 (`docs/sprints/workspaces-collab/01-concept.md`)

## Context

Until W3 a note was shared through `notes.shared_with_ids`: anyone on the list, and every
member of a `workspace`-visible note, could change it, and transcripts were gated by nothing
but `asr.read`. Widening who can see a note was unsafe without roles and transcript gating.

## Decision

1. **Effective access = the highest of** the author team (manage), a per-note collaborator role
   (`note_collaborators`: view | comment | edit, migration 0073), the workspace grant of a
   `workspace`-visible note (member → edit, viewer → comment, guest → none), owner/admin
   (manage) and auditor oversight (view). One function, `note_service.domain.access.level`;
   routes ask `require_view / comment / edit / manage`. Unseen = 404, seen-but-too-low = 403
   `insufficient_role {required}`. `viewer` loses `note.write`; comments need only `note.read`.
2. **Guests are memberships** (`role='guest'`, token role `guest`: tenant/note/notification
   only — no asr, dictation, templates, autocomplete). A guest's search sees only its grants.
   A guest is invited to one note through the W2 entity (`tenant_invitations.note_id`, `role
   guest`, `note_role`); accepting grants the row through `public.grant_note_collaborator`, the
   one sanctioned cross-service write (SECURITY DEFINER, checks the accepted invitation).
   `public.can_manage_note` lets a note's authors (not only workspace managers) invite. A guest
   with no grant left for a day is suspended by auth-service's `sweep-guests`.
3. **Transcript access is decided by the note, enforced where the transcript lives.**
   `public.note_access_for_job` (0075, plain SQL under the caller's RLS): edit or above, or any
   reader once `notes.transcript_shared` is on. A job linked to a note the caller cannot see is
   a row with level NULL (never "no row", which would fall back to `asr.read`); asr-service
   answers 404. Audio clips follow the same rule in note-service, re-checked on stream.
4. **Default visibility** comes from the workspace kind and the meeting family
   (`Family.default_visibility`): team → workspace, personal or one-on-one/interview/memo →
   private. Existing notes are untouched.
5. **Comments** are plain rows anchored by section/item key; **presence** is a Redis sorted set
   with a 45 s window. No real-time co-editing; the 409 version banner stays.

## Options considered

- **Workspace visibility as a role picker** ("everyone: can edit/comment"). More surface for
  the same value; a W4 candidate if asked for.
- **An HTTP call from asr-service to note-service per read**, or a shared grant secret. A new
  network dependency on the hot path, or a new secret to rotate. Rejected for one SQL function.

## Consequences

- `notes.shared_with_ids` is unwritten (rollback only); W4 drops it.
- `POST /v1/notes/{id}/share/email` keeps `mode: "link"` as its default so shipped clients
  still mail outsiders a recipient link; `mode: "invite"` returns `invite_needed` instead.
- `?purpose=` is still not required on `ask` and `diff` (clients do not send it yet).
