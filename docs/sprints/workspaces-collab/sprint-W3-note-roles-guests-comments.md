# Sprint W3 — Share a note with people: roles, guests, comments

**Duration:** 2 weeks · **Team:** 1 backend (note-service, asr-service), 1 web, 1 Swift (iOS + macOS), ½ floating (isolation suite, perf check on search)
**Depends on:** W1 (`guest` known everywhere, sessions switch); W2 for one task only (inviting an address that is not a member — reuses `tenant_invitations.note_id`). Every other task can start after W1.
**Unblocks:** W4 (drops `shared_with_ids`).
**Concept:** `00-concept-workspaces-and-collaboration.md` §3 (jobs 2–4), §5, decisions 5–8.
**Priority:** P0 — widening who can see a note is unsafe until roles and transcript gating exist, so this sprint ships them together.

## Sprint outcome

> A note's author gives people access by role — **view**, **comment**, **edit** — from one dialog, whether they are in the workspace, in another workspace, or have no account yet. Viewers read; commenters leave anchored comments; editors change the text with the existing version rules. A note shared in a team workspace is visible to its members by default and editable by members, commentable by viewers. Transcript and audio follow the role, enforced where the transcript lives. A guest sees the notes they were given and nothing else, in a workspace that shows up on their switcher as "Guest in Acme". Everyone with access sees who else is looking at the note right now and finds shared notes under "Shared with me".

**Demo:** author shares a client-call note with a colleague as *comment* → she opens "Shared with me", comments on a decision, types in the body → the field is read-only → author sees "Anna is viewing" and her comment with a jump to the section → author shares the same note with `tom@client.com` as *view* → Tom signs up → sees that one note, no transcript tab, no "Everyone in the workspace" → `GET /asr/jobs/{job}/result` with Tom's token → 404 → author toggles "Include transcript" → Tom sees it → author removes Tom → Tom's next load is "not available" and his switcher no longer lists Acme.

---

## Inspect first (stop and report if any is false on your branch)

1. `services/note-service/src/note_service/domain/access.py` has `sees_whole_tenant`, `is_author_team`, `reads_as_collaborator` (author team **or** `claims.sub in note.shared_with_ids`), `can_view`, `can_manage`, `can_delete`, `require_view/manage/delete`, `require_read_purpose`; there is no `require_edit`.
2. `routers/notes_drafts.py:96` `PUT /v1/notes/{id}/draft` guards with `require_view`; `routers/notes_lifecycle.py:61` `POST /{id}/cancel` too. Item corrections, `PATCH /items`, generation, meeting job routes use `require_manage`.
3. `notes.visibility note_visibility ('private','workspace')`, `notes.shared_with_ids UUID[]` (0016); `notes_repository.add_shared_with / remove_shared_with` (`:137/:149`); `create_note_with_v1` (`:760`) never sets visibility (DB default `private`).
4. `domain/search.py:39 _access_clauses` builds `(n.visibility = 'workspace' OR n.primary_author_id = $i OR $i = ANY(n.co_author_ids) OR $i = ANY(n.shared_with_ids))`; `routers/notes_search.py:116` passes `viewer_sees_all=access.sees_whole_tenant(claims)`.
5. `routers/notes_sharing.py`: `GET /{id}/sharing` → `SharingView{visibility, can_manage, can_delete, shared_with:[Member{sub,email,display_name}], public_link, links, constraints}`; `POST /{id}/share {email}` resolves only active members via `profile_of_subs`; `DELETE /{id}/share/{sub}`; `POST /{id}/share/email` (members get access, outsiders get a recipient link).
6. asr-service `routers/jobs.py:559` `GET /asr/jobs/{job_id}/result` and `:1833` `GET /asr/jobs` require `asr.read` only; `repository.get_job_and_result_uri` is a tenant-RLS `SELECT`. A note links to its job by `notes.source_asr_job_id` or `note_meetings.asr_job_id` (0049); dictation notes by `dictation_sessions.audio_file_id`.
7. `routers/notes_audio.py` (clips per section) and `routers/audio_clips.py:68` (`POST /v1/audio-clips`) guard with `require_view` + read purpose; `GET /v1/audio-clips/{id}?t=` is authenticated and verifies the HMAC against `claims.tid` (`audio_clips.py:199-212`) but never re-checks the note.
8. `libs/auth/src/auth/perms.py`: `viewer` has `note.write`; `guest` is in `KNOWN_ROLES` with no ALLOW rows (W1).
9. `notification_events.Category.NOTE_SHARED_WITH_YOU` exists with `ALLOWED_PAYLOAD_KEYS = {note_code, shared_by_display}`; no comment category.
10. Web `components/ShareDialog.tsx` (702 lines; sections Send / People with access / General access; `shareWithMember` exported from `api/notes.ts` but unused); `pages/NotesPage.tsx` has no ownership filter; `NoteEditorPage.tsx:1631` `editable = isDraft && !viewing`. iOS/macOS `NoteView.swift` ⋯ menu + `NoteViewModel.loadSharing`; no "People with access" list natively.
11. `domain/meeting_doc/types.py:52` `Family.default_visibility` is referenced only by a test.
12. W2's `tenant_invitations` has `note_id`, `note_role` (if W2 has not landed, the "invite a non-member to a note" task is deferred, not re-implemented).
13. Next free migration numbers (three migrations here); ADR next number.

---

## Scope

1. `note_collaborators` (role view/comment/edit) replaces the array in code; backfill; `access.py` gains `can_comment`, `can_edit`, `require_edit`, `require_comment`; every write route re-guarded; `viewer` loses `note.write`; `guest` gets its permission rows.
2. Default visibility: `workspace` for new notes in team workspaces, `private` in personal and for sensitive families.
3. Sharing API v2: grant/change/revoke by role, pending invitations on the note, transcript inclusion toggle; the Share dialog rebuilt on web and built natively.
4. Guests: per-note invitation of a non-member (W2 entity) creates a `guest` membership + collaborator row on accept; guest-aware search, switcher label, capability hiding.
5. Transcript/audio gating: a note-owned SQL function `note_access_for_job` used by asr-service result/list/speaker routes and by note-service clips.
6. Comments: table, routes, anchored UI, notification.
7. Presence: Redis TTL set + heartbeat + viewer list.
8. "Shared with me" and "Mine" filters in search and on every client.
9. Isolation suite walked as `view`, `comment`, `guest`, and a workspace `viewer`.

## Explicit non-scope

- Real-time co-editing, cursors, merge of conflicting drafts (keep the 409 banner).
- @-mentions, reactions, threads, e-mail reply to comments, comment on the shared *recipient* page (that page keeps its responses).
- Per-section permissions; sharing a space/folder.
- Dropping `shared_with_ids` (W4 — this sprint stops writing it; `notes_repository.add_shared_with/remove_shared_with` are deleted; reads switch to the table; the column stays for rollback).
- Changing the recipient-link path (`shared_public.py`) beyond revoking links when a note is deleted (exists).
- Workspace-level setting for "members can edit workspace-visible notes" — decision 6 is fixed for this sprint; a setting is a W4 candidate if asked for.

---

## G-1 Design decisions

**Roles are per note and per person; workspace visibility is a second, coarser grant.** Effective access = max(collaborator role, visibility grant for the person's workspace role). The matrix:

| Person | `private` | `workspace` |
|---|---|---|
| author team (`primary_author_id`, `co_author_ids`) | manage | manage |
| collaborator `edit` / `comment` / `view` | that role | max(that role, below) |
| workspace `owner`/`admin` (token `tenant_admin`+`member`) | manage (oversight read with purpose, as today) | manage |
| workspace `member` | — | edit |
| workspace `viewer` | — | comment |
| workspace `guest` | — | — |

"manage" = edit + share + visibility + delete-if-primary-author. **Rejected:** making workspace visibility a role picker ("everyone: can edit / can comment") — more surface for the same first-version value; recorded as the W4 candidate above.

**Guests are memberships.** A guest row in `tenant_memberships` means RLS (`app.tenant_id`), `profile_of_subs`, notifications, the switcher and `POST /auth/token` all work unchanged. The token role `guest` has `note.read`, `note.write` (needed by the `edit` collaborator role; `require_edit` decides), `notification.read/write`, `tenant.read` — **no** `asr.*`, `dictation.*`, `template.*`, `autocomplete.*`, `stats.read`, `nlp.*`. A guest's search sees only rows with a collaborator grant. A guest with no remaining grants is removed from the workspace by the sweeper (membership deleted, audit `tenant.member_removed {reason:"no_grants"}`) — not immediately, so an author who re-shares within a day does not re-invite.

**Transcript access is decided by the note, enforced by the service that holds the transcript.** `public.note_access_for_job(p_job_id uuid, p_sub uuid, p_roles text[]) RETURNS text` (`'manage'|'edit'|'comment'|'view'|NULL`, plus `include_transcript` via a second OUT column) is a plain SQL function (not SECURITY DEFINER — it runs under the caller's tenant RLS) owned by note-service's migration and executed by asr-service. Transcript rule: `manage`/`edit` → yes; workspace `member` on a `workspace` note → yes; `comment`/`view`/`guest` → only when `notes.transcript_shared = true`. A job with **no** linked note (upload-only transcription) keeps today's rule (`asr.read`, requester or any member). **Rejected:** an HTTP call from asr-service to note-service per read (a new network dependency on the hot path); a shared HMAC grant secret (a new secret to rotate). One database, one function, no secret.

**Comments are plain rows, anchored by key.** `note_comments(anchor_kind section|item|note, anchor_key)` reuse `section_key` and `item_key` (the content-hash linkage from Sprint 35), so a comment survives re-rendering and shows as "on a line that was removed" when its key disappears. Bodies are text, rendered as text, ≤ 2 000 chars. Edit by author within the note's rules; resolve by anyone with `edit`; delete by author or `manage`.

**Presence is a Redis set with TTL, nothing more.** `note:presence:{tid}:{note_id}` → members `sub`, each refreshed by `POST /v1/notes/{id}/presence` every 20 s while the note is open (clients already poll jobs at 3 s; this is cheaper), `EXPIRE 45`. `GET /{id}/presence` returns display names via `profile_of_subs`. Fail-open: Redis down → empty list.

**Default visibility is set at creation from the workspace kind and the family**, in `create_note_with_v1`'s callers through one helper `domain/visibility.default_for(tenant_kind, family)`. Existing notes are untouched (they were backfilled to `workspace` in 0016 and later ones defaulted to `private`; both are the author's to change).

---

## Data model

### Migration A `00NN_note_collaborators.sql` (+ down)

```sql
CREATE TYPE note_collab_role AS ENUM ('view','comment','edit');
CREATE TABLE note_collaborators (
    note_id     UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_sub    UUID NOT NULL,
    role        note_collab_role NOT NULL,
    granted_by  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, user_sub)
);
CREATE INDEX note_collaborators_user_idx ON note_collaborators (tenant_id, user_sub);
-- RLS: five policies of 0021_note_spaces.sql; DELETE allowed to app_role (revoke is a hard delete; audit carries the history).
ALTER TABLE notes
    ADD COLUMN transcript_shared BOOLEAN NOT NULL DEFAULT false;   -- "Include transcript" for view/comment/guest
-- Backfill: today's sharees could edit, so they keep edit.
INSERT INTO note_collaborators (note_id, tenant_id, user_sub, role, granted_by)
SELECT n.id, n.tenant_id, s.sub, 'edit', n.primary_author_id
FROM notes n, unnest(n.shared_with_ids) AS s(sub)
ON CONFLICT DO NOTHING;
COMMENT ON COLUMN notes.shared_with_ids IS 'DEPRECATED W3: read note_collaborators; dropped in W4';
```
Run the backfill with `tenant_writer` (cross-tenant insert; `tenant_writer` has no `app_role` restrictive policy on new tables only if the policies grant it — copy the `tenant_memberships_writer_all` pattern for this table so the one-off backfill and the W4 drop can run). Down: drop table + column + type.

### Migration B `00NN_note_comments.sql` (+ down)

```sql
CREATE TABLE note_comments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id      UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    author_sub   UUID NOT NULL,
    anchor_kind  TEXT NOT NULL CHECK (anchor_kind IN ('note','section','item')),
    anchor_key   TEXT NOT NULL DEFAULT '' CHECK (char_length(anchor_key) <= 200),
    body         TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    edited_at    TIMESTAMPTZ,
    resolved_at  TIMESTAMPTZ, resolved_by UUID,
    deleted_at   TIMESTAMPTZ, deleted_by UUID
);
CREATE INDEX note_comments_note_idx ON note_comments (note_id, created_at) WHERE deleted_at IS NULL;
-- RLS: five policies; DELETE USING (false) (soft delete).
```
Comment bodies are content: cascade on note delete, included in DSAR export (`scripts/ops/` runbook entry), never logged. Down: drop.

### Migration C `00NN_note_access_for_job.sql` (+ down)

```sql
CREATE FUNCTION public.note_access_for_job(p_job_id uuid, p_sub uuid, p_roles text[])
RETURNS TABLE (level text, transcript boolean) LANGUAGE sql STABLE AS $$
  WITH linked AS (
    SELECT n.* FROM notes n
    WHERE n.deleted_at IS NULL AND (n.source_asr_job_id = p_job_id
       OR n.id IN (SELECT note_id FROM note_meetings WHERE asr_job_id = p_job_id))
  ), ranked AS (
    -- rank: 4 manage, 3 edit, 2 comment, 1 view
    SELECT n.id, n.transcript_shared, GREATEST(
      CASE WHEN p_sub = n.primary_author_id OR p_sub = ANY(n.co_author_ids) THEN 4 END,
      CASE WHEN 'tenant_admin' = ANY(p_roles) AND 'member' = ANY(p_roles) THEN 4 END,
      (SELECT array_position(ARRAY['view','comment','edit'], c.role::text)
         FROM note_collaborators c WHERE c.note_id = n.id AND c.user_sub = p_sub),
      CASE WHEN n.visibility = 'workspace' AND 'member' = ANY(p_roles) THEN 3
           WHEN n.visibility = 'workspace' AND 'viewer' = ANY(p_roles) THEN 2 END) AS rank
    FROM linked n)
  SELECT (ARRAY['view','comment','edit','manage'])[rank] AS level,
         (rank >= 3 OR transcript_shared) AS transcript
  FROM ranked WHERE rank IS NOT NULL ORDER BY rank DESC LIMIT 1
$$;
```
`GREATEST` ignores NULLs, so a person with no grant yields no row. A unit test covers the matrix above. `GRANT EXECUTE … TO app_role`. The function reads `notes`, `note_meetings`, `note_collaborators` under the caller's RLS — a tenant-B caller gets no rows. Returns zero rows when no note links to the job (asr-service then applies today's rule).

---

## Backend — note-service

### B-1 `domain/access.py`

```python
def collaborator_role(note, sub) -> str | None            # from NoteRow.collaborators (loaded with the note)
def workspace_grant(note, claims) -> str | None           # 'edit' member / 'comment' viewer when visibility == workspace; None for guest
def level(note, claims) -> str | None                     # 'manage' | 'edit' | 'comment' | 'view' | None, per the matrix
def can_view / can_comment / can_edit / can_manage / can_delete
def require_view(note, claims) -> NoteRow                 # 404
def require_comment / require_edit / require_manage       # require_view then 403 {code: "insufficient_role", "required": "edit"}
def can_read_transcript(note, claims) -> bool             # level in (manage, edit) or workspace_grant == 'edit' or note.transcript_shared
```
`NoteRow` gains `collaborators: list[Collaborator{sub, role}]` (one extra query in `fetch_note`, or a lateral join — measure; `fetch_note` is on every route) and `transcript_shared`. `reads_as_collaborator` keeps its name (read-purpose logic) and reads the table.

Re-guard: `PUT /{id}/draft`, `POST /{id}/cancel`, `PATCH /items/{id}`, item corrections (`_editable`), `my-notes/timing`, generation `POST`, `PUT /{id}/space` (missing today — `require_view`), `POST /{id}/ask` (`require_view` + purpose), `GET /{id}/diff` (purpose). A table in the PR description lists every route and its guard; `tests/unit/test_note_access.py` grows a parametrised matrix over {author, co-author, edit, comment, view, member, viewer, guest, admin, stranger} × {private, workspace} × {view, comment, edit, manage, delete, transcript}.

### B-2 Sharing API v2 (`routers/notes_sharing.py`)

| Method | Path | Guard | Body / result |
|---|---|---|---|
| GET | `/v1/notes/{id}/sharing` | `require_view` | `SharingView` + `my_level`, `people: [{sub, email, display_name, level: manage|edit|comment|view, source: author|collaborator|workspace_role, membership_role, can_change: bool}]`, `pending: [{invitation_id, email_masked, note_role, expires_at}]` (manage only), `transcript_shared`, `visibility`, `workspace_kind`. `shared_with` kept one release for old clients (= people with `source=collaborator`). |
| PUT | `/v1/notes/{id}/collaborators/{sub}` | `require_manage` | `{role}` → 200 upsert; 404 `not_a_member` when `sub` has no active membership here (guests included); 409 `is_author` |
| DELETE | `/v1/notes/{id}/collaborators/{sub}` | `require_manage` | 204; audit `note.unshared`; if the person is a `guest` with no other grants, nothing more now (sweeper) |
| POST | `/v1/notes/{id}/share` | `require_manage` | `{email, role: view|comment|edit, message?}` → member: upsert collaborator + `note.shared_with_you` (payload gains `role`), 201 `{kind:"granted"}`. Non-member: `404 not_a_member {can_invite: true}` — note-service has no auth-service client and may not mail non-members (README rule), so the **client** then calls auth-service `POST /tenants/{tid}/invitations {email, role:"guest", note_id, note_role}` (W2 route, extended to accept `note_id`). On accept, auth-service inserts the collaborator row through `public.grant_note_collaborator(p_note, p_sub, p_role, p_by)` — SECURITY DEFINER, note-service-owned, verifies an accepted invitation row with that `note_id` exists for the identity under the same tenant; the one sanctioned cross-service write, built on the same philosophy as `profile_of_subs`. |
| PUT | `/v1/notes/{id}/visibility` | `require_manage` | existing; `workspace` refused with 409 `personal_workspace` when `tenants.kind='personal'` |
| PUT | `/v1/notes/{id}/transcript-sharing` | `require_manage` | `{shared: bool}` → audit `note.transcript_sharing_changed` |
| POST | `/v1/notes/{id}/share/email` | `require_manage` | existing route; body gains `role` for members; outsiders still get a recipient link **only if** the caller chose "Send a link" (`mode:"link"`); default `mode:"invite"` returns the `not_a_member {can_invite}` shape above. |

Guards also change in asr-service (B-5). `note.shared` audit payload: `{with, via, role}`.

### B-3 Search (`domain/search.py`, `routers/notes_search.py`)

`_access_clauses`: replace the array predicate with `EXISTS (SELECT 1 FROM note_collaborators c WHERE c.note_id = n.id AND c.user_sub = $i)`; for a `guest` token **only** that clause (no `visibility='workspace'`, no author clause — a guest authors nothing here). New filters `scope=mine|shared_with_me|all` (`mine` = author clauses; `shared_with_me` = collaborator **or** (visibility workspace and not author) — "notes I can see that are not mine"). `exact_total` honours the filters (fixes the `author_id` bug noted in the audit). Hits gain `my_level` and `collaborator_count` (replacing `cardinality(shared_with_ids)`). `EXPLAIN` on a 50 k-note tenant in the perf check: the `note_collaborators_user_idx` must be used; p95 of `/search` within +10 % of today (guardrail).

### B-4 Comments (`routers/notes_comments.py` new, `domain/comments_repository.py`)

| Method | Path | Guard | Body / result |
|---|---|---|---|
| GET | `/v1/notes/{id}/comments` | `require_view` | `{items:[{id, author:{sub, display_name}, anchor_kind, anchor_key, anchor_present: bool, body, created_at, edited_at, resolved_at, resolved_by_display, can_edit, can_resolve, can_delete}]}` — `anchor_present` computed against the current version's section/item keys |
| POST | `/v1/notes/{id}/comments` | `require_comment` | `{anchor_kind, anchor_key?, body}` → 201; audit `note.commented {anchor_kind}`; notification `note.commented` to the author team + other commenters on the same anchor (debounced per note per 5 min per recipient, like `recipient_responded`) |
| PATCH | `/v1/notes/{id}/comments/{cid}` | author of the comment (and still `require_comment`) | `{body}` → `edited_at` |
| POST | `/v1/notes/{id}/comments/{cid}/resolve` / `unresolve` | `require_edit` | 200 |
| DELETE | `/v1/notes/{id}/comments/{cid}` | comment author or `require_manage` | 204 soft |

Rate limit `note:comment-rl:{tid}:{sub}:{hour}` 120/h fail-open. Bodies: `_clean_comment`-style (plain text, URLs allowed as text, no HTML; reuse `shared_public._clean_comment` after extracting it to `domain/text.py`).

### B-5 asr-service gating (`routers/jobs.py`, `domain/repository.py` — `get_job` `:145`, `list_jobs` `:155`, `get_job_and_result_uri` `:424`)

`get_result` (`:559`), `GET /jobs/{id}` (`:534`), all `/speakers/*` writes, `rediarize`, `DELETE /jobs/{id}`: after the existing `asr.read`/`asr.write` check, call `repository.note_access_for_job(conn, job_id, claims.sub, claims.roles)`; if a row comes back: result/transcript reads require `transcript=true` (else `404 job_not_found` — never 403, the job's existence is the note's secret); speaker edits/rediarize/delete require `level IN ('manage','edit')` (403 `insufficient_role`); if no row (unlinked job): today's behaviour. `GET /asr/jobs` (`:1833`) hides jobs whose linked note the caller cannot read (join the function per row — or simpler and sufficient: exclude jobs with a linked note where the caller is not `requester_sub` and the function returns no transcript; measure). Audio download paths that still exist in asr-service (presigned result URL `:551`) follow the same rule. note-service `audio_clips.py` `POST /v1/audio-clips` and `notes_audio.py` use `can_read_transcript` (clips are audio). The web transcript tab (`api/asr.ts getResult`) handles 404 by hiding the tab; `NoteEnvelope` gains `can_read_transcript` so clients do not probe.

### B-6 Presence (`routers/notes_presence.py`)

`POST /v1/notes/{id}/presence` (`require_view`, 204; `SADD` + `EXPIRE 45`), `GET /v1/notes/{id}/presence` (`require_view`; `{viewers:[{sub, display_name}]}` minus the caller). Redis keys `note:presence:{tid}:{note_id}`; fail-open.

### B-7 Guest sweeper (`jobs/guest_sweeper.py`)

Daily: memberships with `role='guest'` that have had no `note_collaborators` row and no pending `tenant_invitations` with `note_id` for 24 h → `tenant_memberships.status='suspended'`, `left_at=now()` (the next refresh heals the person's session to personal through the existing `switch_tenant` path; auth-service owns `auth_sessions`, so no direct revocation from note-service), audit `tenant.member_removed {reason:"no_grants"}`. The row is deleted 30 days later by the same "left" cleanup W2 introduced. `tenant_memberships` is `tenant_writer`-writable only, so this sweeper lives in **auth-service** (`ops/` CLI twin + ADR-0041 runner) and reads `note_collaborators`/`tenant_invitations` with `tenant_writer`, which has SELECT on both.

### B-8 Permissions (`libs/auth/perms.py`, `docs/auth/permissions.csv`)

Add: `guest`: `note.read`, `note.write`, `notification.read`, `notification.write`, `tenant.read`. Remove: `viewer`/`note.write` (the resource rule covers `comment`; `viewer` keeps `note.read`). Audit every `requires("note.write")` route to confirm `require_edit`/`require_comment` sits behind it — a `viewer` must still be able to `POST /comments`, so that route requires `note.read` + `require_comment` (not `note.write`).

### B-9 Default visibility

`domain/visibility.py::default_for(tenant_kind, family) -> 'workspace'|'private'`; callers: `POST /v1/notes`, `/meeting`, from-transcript, dictation finalize path (dictation-service forwards the user's bearer to note-service's create — the default is applied server-side in note-service, so dictation needs no change). `tenants.kind` for the current tenant: extend `sharing_policy.load_policy(conn, tenant_id) -> (policy, plan)` (`domain/sharing_policy.py:80`, module-level `_cache` `:64`, 60 s) to also return `kind`, so there is one cached read of the tenant row (`domain/cache.py` is the template cache — not this). Sensitive families (`one_on_one`, `interview`, `memo`) → `private`.

### B-10 Notifications

`note.shared_with_you` payload gains `role` (allow-list); new `note.commented` (`note_code`, `anchor_kind`; in-app + daily digest), `note.access_changed` (to the person whose role changed or was revoked; in-app). CHECK widening if needed (W2's finding).

---

## Web (`web/`)

- **W-1 API/types:** `SharingView` v2, `setCollaborator(noteId, sub, role)`, `removeCollaborator`, `shareNote({email, role, message})` with the `not_a_member {can_invite}` branch calling `invite(tenantId, {email, role:"guest", note_id, note_role})` (W2 client), `setTranscriptSharing`, comments CRUD, presence, `searchNotes({scope})`; `NoteEnvelope.my_level`, `can_read_transcript`.
- **W-2 Share dialog (`components/ShareDialog.tsx`)** rebuilt: *People* — chips input + role select (`view|comment|edit`) + message + "Invite" (copy: "People in your workspace get access now; others get an e-mail and sign in to see this note"); the list shows everyone with access and **why** ("Everyone in the workspace · can edit" row for `visibility=workspace`, "Guest" badge, role select per collaborator, Remove); *Pending invitations* with Revoke; *General access* (`private | workspace`; `workspace` hidden in personal workspaces) + "Include transcript for viewers and commenters" toggle with the explanation line; *Send a link* (recipient link) as the last section, unchanged.
- **W-3 Editor (`pages/NoteEditorPage.tsx`):** `editable = isDraft && my_level ∈ {manage, edit}`; `comment`/`view` get a read-only body with a top strip "You can comment on this note" / "You can view this note" and no capability buttons (generate, items edit, share) — absent, not disabled; transcript tab absent when `!can_read_transcript`; presence avatars in the header (poll `GET /presence` every 20 s while mounted; `POST` heartbeat on the same timer); comments side panel (`components/CommentsPanel.tsx`): list grouped by anchor, "Comment on this section" from each section header and each item row's ⋯ menu, resolved filter, compose box; "on a removed line" state.
- **W-4 Notes list (`pages/NotesPage.tsx`):** segmented filter All / Mine / Shared with me (`scope`), `my_level` chip per row; guests see only "Shared with me" (the server returns nothing else; the UI hides the other segments when `activeRole === "guest"`).
- **W-5 Shell:** guest workspaces in `WorkspaceSwitch` render "Guest in Acme Inc" with a badge; the New-meeting menu, Spaces and Settings › Workspace entries are hidden for guests (`activeRole`), as are Members for non-managers already.
- **W-6 Tests:** share dialog (role upsert; `not_a_member` → invite path; transcript toggle), editor read-only states per level, comments panel (post/resolve/delete permissions from the API flags), notes list scope filter, guest shell.

## iOS (`ios/Sources/NotesAICapture/`)

- `APIClient` endpoints (W-1 set); `Models.swift` `SharingView` v2, `Comment`, `Presence`, `NoteEnvelope.myLevel / canReadTranscript`.
- `Views/ShareSheet.swift` (new; replaces the ⋯ menu's scattered items): People (invite by e-mail + role; list with role menus and Remove; pending), General access, transcript toggle, Send a link (existing `ShareWithClientSheet` entry). `NoteView.swift`: ⋯ → "Share…" opens it; editor read-only per `myLevel` (reuse the existing `viewing` state), transcript tab hidden, presence avatars, comments: a "Comments (n)" button → `CommentsView` (list + compose, anchor from the section/item context menu "Comment…").
- `HomeView.swift`: filter chips All / Mine / Shared with me; `NoteRow` gets the level chip; guest mode hides Record/New and Spaces.
- `WorkspaceView.swift`: "Guest in …" label.
- Offline: comments composed offline are kept in memory until posted (no persistence — a comment is short; the compose box says "Sending…" and retries 3× then shows the text back to the user to copy). Nothing user-authored is lost silently.
- Tests: decoders; `canEdit` from level; guest hides capabilities.

## macOS (`macos/Sources/NotesAICapture/`)

Mirror iOS: `Views/ShareSheet.swift`, `Views/CommentsView.swift`, `NoteView.swift` states, `Sidebar.swift` filter + guest label, `RecentsView.swift` shows the level chip. Shared Swift only for byte-identical files (`clients/Shared/CollaborationModels.swift` if the models are identical — likely).

---

## Security review

- **The widening is gated behind the role rule and the transcript rule; both are server-side and tested per route.** The isolation suite gains personas: `view` collaborator, `comment` collaborator, `edit` collaborator, workspace `viewer`, `guest`, and walks every id route of note-service **and asr-service** with each, asserting the matrix (404 for unseen, 403 `insufficient_role` for seen-but-not-allowed, no state change on refusal). This is the acceptance gate.
- **Guests:** cannot list the roster (`tenant.read` lets `GET /tenants/current` answer name + kind; `GET /tenants/{id}/members` requires `tenant.manage_members` or a member role — verify `_require_member` does not treat `guest` as a roster reader), cannot search beyond grants, cannot record, cannot reach templates/glossary/autocomplete. `profile_of_subs` exposes a guest's display name to members of that workspace (they invited them) — acceptable; documented.
- **Transcript via side doors:** audio clip creation, section clips, presigned result URL, `GET /asr/jobs` listing, `by-source-job` (`notes_from_transcript.py:472` — add `require_view`), `NoteEnvelope.source_job_id` (only returned when `can_read_transcript`). Each is a test row.
- **Cross-service write** (`grant_note_collaborator`): SECURITY DEFINER, checks that an accepted invitation row with that `note_id`/`email` exists for the identity, inserts under the invitation's tenant, grants `EXECUTE` to `tenant_writer` only.
- **Comments:** text only; 2 000 chars; rate-limited; included in deletion cascades and DSAR; `note.commented` notification carries `note_code` + `anchor_kind` only.
- **Presence:** reveals who is viewing to anyone who can view — by design; no history is stored.
- **IDOR on comments:** every comment route re-fetches the note by `(tid, note_id)` and the comment by `(note_id, cid)`.

## Failure scenarios

| Failure | Behaviour |
|---|---|
| `note_access_for_job` raises (e.g. missing function after a partial deploy) | asr-service answers 404 for jobs with a linked note (fail closed) and logs `asr.note_access_unavailable`; alert |
| Redis down | presence empty; comment limiter fail-open |
| Collaborator loses membership (removed/left/suspended) | `fetch_note` loads collaborators with `EXISTS active membership`; stale rows are ignored and removed by the sweeper; audit on removal |
| Edit conflict between two editors | existing 409 `optimistic_lock_mismatch` + banner; the banner now names who saved (`note_versions.created_by` → `profile_of_subs`) |
| Invitation accepted after the note was deleted | `grant_note_collaborator` finds no live note → membership `guest` is still created (workspace invitation semantics) and the sweeper removes it after 24 h; the landing page says "This note is no longer available" |

## Observability

Counters: `mdx_note_share_total{role, kind=granted|invited}`, `mdx_note_access_refused_total{route, level_required}`, `mdx_note_transcript_refused_total{service}`, `mdx_note_comments_total{anchor_kind}`, `mdx_note_presence_viewers` (histogram), `mdx_note_search_scope_total{scope, role}`. Logs: ids, levels, never bodies. Dashboard row "Collaboration" on the notes board; alert when `access_refused_total{route="draft"}` spikes (clients offering edit to the wrong level).

## Tests

| Test | Expected |
|---|---|
| Access matrix (B-1) | every cell |
| Backfill | each `shared_with_ids` entry → one `edit` row |
| `PUT /draft` as `comment` / `view` / workspace viewer / guest | 403 `insufficient_role`; as member on a workspace note → 200 |
| `POST /comments` as `view` | 403; as `comment` → 201; as workspace viewer on a workspace note → 201; as guest with `view` → 403 |
| Search as guest | only granted notes; `scope=mine` empty |
| `scope=shared_with_me` as member | workspace-visible notes by others + grants |
| `note_access_for_job` matrix incl. `transcript_shared` | per the rule; tenant B → no rows |
| asr `GET /result` as `view` without transcript sharing / with | 404 / 200 |
| asr `PUT /speakers` as `comment` | 403 |
| `GET /asr/jobs` as guest | linked-but-unreadable jobs absent |
| Audio clip as `view` without sharing | 404 |
| `POST /share` non-member | 404 `not_a_member {can_invite:true}`; then the W2 invitation with `note_id` → accept → collaborator row + guest membership |
| Visibility `workspace` in personal tenant | 409 |
| Default visibility: team + client_call / personal / team + one_on_one | workspace / private / private |
| Presence heartbeat + list | caller excluded; expires after 45 s (fake clock) |
| Guest sweeper | removes grant-less guests after 24 h; keeps those with pending note invitations |
| Isolation personas walk (note-service + asr-service) | matrix holds; no state change on refusals |
| Web/iOS/macOS unit tests | pass |

## Acceptance criteria (binary)

1. A `comment` collaborator cannot change a note's body on any client or through the API; an `edit` collaborator can; both see the evidence chips.
2. A `view` collaborator and a guest cannot obtain the transcript or an audio clip through any route until the author enables "Include transcript"; after enabling, both can; after disabling, neither can within 60 s.
3. A guest's search, list and switcher show only granted notes and the "Guest in …" workspace; the guest cannot start a recording or open members/settings in that workspace.
4. A member of a team workspace sees a colleague's new client-call note by default and can edit it; a one-on-one note is private by default.
5. Comments anchored to a section survive a regeneration that keeps the section key, and show "on a removed line" when it is gone.
6. "Shared with me" lists exactly the notes the person can see but did not author, on all three clients.
7. Two people with the note open see each other within 45 s and disappear within 60 s of closing it.
8. The isolation persona walk passes for note-service and asr-service; `make test-isolation` passes.
9. `notes_repository.add_shared_with/remove_shared_with` are deleted; nothing writes `shared_with_ids`; `GET /sharing` still returns `shared_with` for old clients.
10. ADR-0071 (per-note roles, workspace-visibility grants, guest memberships, transcript rule), runbook (`notes.md` § collaboration: stuck guest, revoke everything for a person, erase comments), OpenAPI, changelog, dashboard; all CI gates pass; `/search` p95 within +10 %.

## Implementation order

1. Migration A + backfill + `NoteRow.collaborators` → 2. B-8 permissions + B-1 access rules + matrix test → 3. re-guard every write route → 4. Migration C + B-5 asr gating + clip gating → 5. B-2 sharing v2 + `grant_note_collaborator` + W2 `note_id` acceptance hook → 6. B-3 search scopes + perf check → 7. B-9 defaults → 8. Migration B + B-4 comments + B-10 notifications → 9. B-6 presence + B-7 sweeper → 10. web → 11. iOS → 12. macOS → 13. persona isolation walk → 14. ADR/runbook/changelog.

## GitHub issues

| # | Title | Depends |
|---|---|---|
| W3-1 | Migration `note_collaborators` + `transcript_shared` + backfill; `NoteRow.collaborators` | — |
| W3-2 | Access rules v2 (`level`, `require_edit/comment`), permission rows (`guest`, `viewer`), re-guard all write routes, matrix tests | W3-1 |
| W3-3 | `note_access_for_job` + asr-service gating + clip gating + `can_read_transcript` on the envelope | W3-1 |
| W3-4 | Sharing API v2, `grant_note_collaborator`, W2 acceptance hook for `note_id` invitations, audits | W3-2, W2-4 |
| W3-5 | Search scopes + guest clause + `exact_total` fix + perf check | W3-2 |
| W3-6 | Default visibility helper + callers | — |
| W3-7 | Comments: migration, routes, notifications, limiter | W3-2 |
| W3-8 | Presence (note-service) + guest sweeper (auth-service) | W3-2 |
| W3-9 | Web: share dialog, editor levels, comments panel, scopes, guest shell, tests | W3-3..W3-8 |
| W3-10 | iOS: share sheet, comments, levels, filters, guest mode | W3-3..W3-8 |
| W3-11 | macOS: same | W3-3..W3-8 |
| W3-12 | Isolation persona walk (note + asr), ADR-0071, runbook, changelog, dashboard | all |

## Report back

State: the three migration numbers; `fetch_note` cost change (p95 before/after on the dev dataset) and the search p95 delta; whether W2's `note_id` acceptance hook was available (else the deferred task list); the final route→guard table; any "Inspect first" fact that differed; debt found (expected: `GET /v1/notes/by-source-job` had no visibility check; `CreateNoteRequest.co_author_ids` is accepted without a membership check — fix it here only if it blocks the matrix, else document).
