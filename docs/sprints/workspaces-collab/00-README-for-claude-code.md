# Workspaces & collaboration — build sprints for Claude Code

**What this is:** four work orders that make one promise true: *a person has one account, any number of workspaces, and can bring anyone — colleague or outsider — into a workspace or a single note, with the access they were given and nothing more.* Figma's model: one login, personal space, teams you create and name, files shared to people by role, guests who see only what they were invited to. "Organization" is an optional shell above workspaces for billing and admin, added last and only as an experiment.

**Status of the repo (checked on branch `dev`, commit `45a680e`, 2026-10-05; re-verify the "Inspect first" facts on the branch you build on): more exists than the founder's description assumed, but it is switched off, and the parts that are missing are the ones users can see.**

| Exists today | Where | What it does | What it does not do |
|---|---|---|---|
| One identity, many memberships | `infra/postgres/migrations/0001_identity_and_tenancy.sql` (`tenant_memberships`, `UNIQUE (tenant_id, user_sub)`, roles `owner/admin/member/assistant/viewer`), `0024_idx_identities.sql` (`identities`, `auth_sessions.tenant_id`, `tenants.kind personal/team/platform`) | The schema is already many-to-many; a session carries the current workspace; the personal workspace is created with the identity (`identity_repository.create_with_personal_workspace`, `:358`) | **Only in `MDX_IDP_MODE=dual|native`. Every deployment runs `keycloak`** (`.env.example:128`, `docker-compose.override.yml:125`), where `tid` is a fixed Keycloak user attribute and nobody can switch |
| Workspace switching | `POST /auth/token {tenant_id, activate}` (`services/auth-service/src/auth_service/routers/session_native.py:244`, `domain/session_service.py::switch_tenant` ~`:333`), audit `auth.tenant_switched` | Re-mints the access token for another membership, records `identities.last_tenant_id`, refuses `not_a_member / membership_suspended / tenant_dissolved` | Nothing for web multi-tab drift (see W1); `GET /auth/me.db_user` is still read from the legacy single-tenant `users` row |
| Switcher on all three clients | web `web/src/shell/AppShell.tsx:182` (`WorkspaceSwitch`, inside the account menu, hidden under Keycloak via `canSwitchWorkspaces`, `web/src/auth/AuthContext.tsx:350`); iOS `Views/WorkspaceView.swift` (`WorkspaceChip`, `WorkspacePicker`); macOS `Views/Sidebar.swift:248` + `Views/WorkspaceViews.swift` | Lists `GET /tenants`, switches, scopes local state by `(identityId, tenantId)` (`LocalScope`/`StateScope`), borrows tokens for uploads that finish in another workspace | No "Create workspace"; no workspace name in the web sidebar header; appears only with ≥ 2 workspaces |
| Member management | `routers/tenants.py` (`GET/POST/PATCH/DELETE /tenants/{id}/members`), web `pages/settings/MembersSettingsPage.tsx`, iOS `Views/InviteView.swift` | Adds an **existing** user by e-mail (resolved through the legacy `users` table, `tenants_repository.resolve_sub_by_email`) | **No invitation entity, no e-mail, nothing for an address without an account** (404 "no user with that email"). `POST /admin/users/invite` (`routers/admin.py:57`) creates a Keycloak user + `users` row only — no identity, no membership, no mail. Native apps parse `notesai://invite/<token>` and say "not supported yet" |
| Note sharing inside the workspace | `notes.visibility private/workspace`, `notes.shared_with_ids UUID[]` (`0016_note_sharing.sql`); `services/note-service/src/note_service/domain/access.py`; `routers/notes_sharing.py`; web `components/ShareDialog.tsx` | A share grants read; `visibility=workspace` makes every member a reader | **No per-share role: anyone who can view can edit** (`PUT /{id}/draft` uses `require_view`, `routers/notes_drafts.py:96`). No comments. No guests. ASR transcripts are not gated by the note at all (`asr-service routers/jobs.py:559` needs only `asr.read`) |
| Sharing outside the workspace | `note_share_links` (kinds `public`, `recipient`), `routers/shared_public.py`, OTP, responses | A no-account recipient page (viral-loop track) | Not collaboration: no identity, no edit, no comments beyond a 280-char response |
| Organizations | — | — | Nothing. No table, no column, no route |

Also found while reading (not this track's job, but it blocks a safe beta — W1 carries the two marked ★): ★ `0013_seed_dev_tenants.sql` inserts "Acme Inc" and "Globex Corp" and `scripts/db/migrate.py` has no production skip, so **every environment gets the demo tenants**; ★ `infra/keycloak/realm-export.json` contains a plaintext password for the founder account; web local storage keys are not workspace-scoped (`lib/captures.ts`); the notification WebSocket registry is keyed by user only (`services/notification-service/src/notification_service/ws/handler.py:40`), so a socket in workspace B receives workspace A's frames; iOS `CaptureViewModel.syncPendingMeetingNotes()` (`:568`) ignores `PendingMeetingNote.tenantId` and can create an offline-typed note in the wrong workspace.

| Sprint | Builds | Depends on | Result you can see |
|---|---|---|---|
| `W1` | Identity cut-over to the native session model on dev/staging; personal workspace guaranteed for every identity; `me`/roster/e-mail lookups moved off the legacy `users` row; the four wrong-workspace bugs fixed; role vocabulary unified; demo seeds out of production | — | Sign in with an e-mail code → land in "Personal" → switch to "Acme" in the sidebar, in the iOS chip, in the macOS menu → every tab, upload and notification follows |
| `W2` | Create / rename / leave / dissolve a workspace on all clients; invitations by e-mail for people with or without an account; pending invitations; accept on web and by deep link; member roster parity on native | W1 | "New workspace → *Sunrise Studio* → Invite tom@client.com (member)" → Tom gets a mail → signs up → lands in Sunrise Studio |
| `W3` | Per-note access by role (view / comment / edit), guests, comments, presence, "Shared with me", transcript/audio gated by the note, viewers cannot edit | W1 (W2 for inviting a non-member to a note) | Share a note with a colleague as *comment* → she sees it under "Shared with me", comments on a decision, cannot type in the body; share with an outsider as *view* → he signs up, sees that one note and nothing else |
| `W4` | Optional organization shell (billing + admin + directory + policy defaults), the native-mode flip, bridge-table retirement, GA hardening, kill criteria | W1–W3 | An owner groups three workspaces under "Acme GmbH", sets the plan once, sees all members in one list; a `shared_with_ids` column no longer exists |

W1 must finish before anything else. W2 and W3 can run **in parallel** after W1 (W3's "invite an outsider to a note" task waits for W2's invitation entity; everything else in W3 does not). W4 starts only after the W2/W3 reviews and only if the concept's §10 gate for organizations is met; its GA items (native flip, bridge retirement) run regardless.

## How to run a sprint with Claude Code

One sprint = one branch = one session. From the repo root:

```
git checkout dev && git pull && git checkout -b workspaces/W1
claude
```

Paste as the first message (change the file name per sprint):

```
Read docs/sprints/workspaces-collab/00-README-for-claude-code.md and docs/sprints/workspaces-collab/sprint-W1-identity-cutover-and-multi-workspace-foundation.md.
Do section "Inspect first" before writing code. If a listed fact is false in this checkout, stop and tell me which one.
Then do the tasks in order. After each task run its "verify" command and fix failures before moving on.
Do not do anything listed under "Explicit non-scope". Do not refactor unrelated code.
Finish with the "Report back" block. Do not commit; leave the working tree for my review.
```

Copy this folder to `docs/sprints/workspaces-collab/` first if it is not already there.

## Repo rules the agent must follow

CI gates: `make lint`, `make lint-imports`, `make typecheck`, per-package `uv run --project … pytest`, `make check-rls`, `make check-identity-bridge`, `make check-identity-grants`, `make check-auth-issuer-config`, `make check-no-direct-asyncpg`, `make check-no-object-storage`, `make check-no-os-environ`, `make check-audit-insert`, `make check-metric-names`, `make check-notification-pii-free`, `make openapi-check` (regenerate with `make openapi-dump`), `make test-isolation` (two-tenant walk of every id route, `tests/integration/test_two_tenant_isolation.py`). Web: `npm run typecheck`, `npm test`, `npm run check:no-danger`. Native: `ios/scripts/check.sh`, `macos/scripts/make-app.sh` — **build only, never launch** (`ios/CLAUDE.md`, `macos/CLAUDE.md`). Plus, specific to this pack:

| Rule | Why |
|---|---|
| **No AI attribution anywhere** — commits, PRs, ADRs, docs, comments carry human authors only (`CLAUDE.md`). | Repo rule |
| `app_role` never reads `identities`. The only paths from a product service to a person are `public.profile_of_subs()` (0027) and whatever SECURITY DEFINER function a sprint here adds with the same "active membership in `app.tenant_id`" boundary. `make check-identity-grants` enforces it. | IDX-B2 boundary |
| Every new table: `tenant_id`, `ENABLE` **and** `FORCE ROW LEVEL SECURITY`, the five policies of `0021_note_spaces.sql`, narrow `GRANT`s, and a row in `_ENTITY_TABLES` of `libs/db/tests/integration/test_rls_isolation.py`. | `make check-rls`, isolation suite |
| Tables that must be read across workspaces by auth-service (`tenant_invitations`, `organizations`) follow the `tenant_memberships` pattern: `tenant_writer` full access, `app_role` SELECT scoped to `app.tenant_id` only. | One cross-tenant reader, and it is auth-service |
| Migrations `infra/postgres/migrations/NNNN_name.sql` + `.down.sql`; `NNNN` = next free on your branch (`0071` if `dev` is still at `0070_billing_interval`). Never edit an applied file. | `scripts/db/migrate.py` checksums |
| A workspace is a `tenants` row. Keep the table and the `tenant_id` column names; say "workspace" in every route summary, UI string, audit payload key and doc. Never introduce a second table called `workspaces`. | One concept, two names is bad; two tables is worse |
| Authorization is `libs/auth/perms.py` (role → action) **then** `note_service/domain/access.py` (resource rule). New per-note rules go into `access.py`; never inline `if role == …` in a router. | CTO rules §13 |
| Every token that changes workspace goes through `POST /auth/token`; no client ever stores a `tid` it did not get from that endpoint or from sign-in. | IDX-M2 contract |
| Audit payloads carry ids and closed vocabularies only — never an e-mail address, a name, a token, a comment body. `docs/audit/event-kinds.md` gets a row per new kind. | Existing rule |
| Mail to someone who is not yet a member goes through `auth_mail_outbox` (auth-service) — never from note-service, which may only mail members and recipient links (ADR-0031/0049). | Mail boundary |
| Feature flags are `MDX_…` settings checked inside the handler; an off feature answers **404**. | Convention |

## Decisions already made (do not reopen in a sprint)

1. **Workspace = tenant.** No new table. Organization is a new, optional parent (`organizations`, `tenants.organization_id NULL`) — W4, gated.
2. **The native session model is the identity model.** Keycloak mode is retired for people (W1 moves dev/staging to `dual`, W4 to `native`); Keycloak stays only where `routers/oauth.py` / service credentials still need it, and only until W4 says otherwise. There is no third model.
3. **Every identity has exactly one personal workspace** (`tenants.kind='personal'`), created with the identity, never deletable, never joinable, shown as "Personal". Team workspaces are `kind='team'`.
4. **Workspace roles are `owner`, `admin`, `member`, `viewer`, `guest`.** `assistant` stays in the CHECK as legacy and is offered nowhere. `guest` is a membership (so RLS, `profile_of_subs`, notifications and switching all work unchanged) whose token role `guest` can reach only notes it was explicitly given.
5. **Per-note access is a table, not an array.** `note_collaborators(note_id, user_sub, role view|comment|edit)` replaces `notes.shared_with_ids`; the array is backfilled (as `edit`, today's effective behaviour) and dropped in W4.
6. **Default visibility in a team workspace is `workspace`** (members: edit; viewers: comment; guests: nothing); in the personal workspace it is `private`. Meeting families marked sensitive (`domain/meeting_doc/types.py::Family.default_visibility`) stay `private`. The author can always change it.
7. **Collaborators see the note and its evidence chips. Transcript and audio clips are visible to `edit` collaborators and workspace members; `view`/`comment` collaborators and guests see them only when the author turns "Include transcript" on for that note.** Enforced in asr-service through a note-owned SQL function, not by trusting the client.
8. **No real-time co-editing.** Edits stay versioned with `expected_version` → 409 and the existing "newer version" banner; presence ("Anna is viewing") is a Redis TTL set. No CRDT, no OT, no sync server.
9. **Invitations are one entity for every case** (`tenant_invitations`, optional `note_id`): existing account or not, workspace or note. Accepting is always an authenticated act by the invited address; nothing is granted on click alone.
10. **Outsiders need an account.** The no-account recipient link stays as the read-only, no-signup path; "invite" always means an identity.
11. **Plan limits stay recorded, not enforced** (`tenants.plan_limits`, Sprint 21 decision) — W2 shows the seat meter, nothing blocks an invite. Enforcement is a pricing decision outside this track.
12. **The demo tenants are dev fixtures.** `0013` is gated out of production in W1; nothing in this track depends on "Acme".
