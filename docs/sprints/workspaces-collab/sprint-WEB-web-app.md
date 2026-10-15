# Sprint WEB — Web app: workspaces, invitations, note collaboration, organizations

**Duration:** 4 phases of ~1 week each, run in step with the backend sprints · **Team:** 1 web engineer (+ ½ floating for e2e/a11y in phases 3–4)
**Depends on:** each phase starts when the matching backend contract is merged (W1 → phase 1, W2 → phase 2, W3 → phase 3, W4 → phase 4). Until then the phase is built against the OpenAPI snapshot in `docs/api/*-openapi.json` with the vitest fetch stubs — nothing in this doc waits for a deployed backend.
**Backend specs:** `sprint-W1…W4`. This document is the single source of truth for web work on this track; the backend sprints only point here.
**Concept:** `00-concept-workspaces-and-collaboration.md` §6 (experience principles).

## Sprint outcome

> The web app shows which workspace you are in at all times, never writes into another one, lets you create a workspace and invite people from where you are, lands an invitee on the thing they were invited to, and turns the Share dialog into the one place where people, the workspace and client links are managed by role. Guests and viewers see a smaller app, not a greyed-out one.

---

## Inspect first (stop and report if any is false on your branch)

1. React 18, react-router 6, Vite, vitest + jsdom (`vite.config.ts` `test.include: ["tests/**/*.test.{ts,tsx}"]`, `tests/setup.ts`), Playwright in `web/e2e/` (`first-use`, `regression`, `shared-page`, `a11y.spec.ts`, `helpers.ts`). No query cache — pages fetch into local state. No i18n library (`web/src/i18n/shared.ts` is for the public page only).
2. `web/src/auth/AuthContext.tsx` holds `me`, `identity`, `memberships`, `activeTenantId`, `activeRole`, `canSwitchWorkspaces` (`:350`, false under a Keycloak issuer), `switchWorkspace` (`:269-286`, calls `activateWorkspace` → `setAccessToken`, `scheduleRefresh`, `setActiveTenantId`), `onRefreshed` (`:181`, reschedules only). `App.tsx` wraps the signed-in tree in `WorkspaceScope` (remount keyed by `activeTenantId`).
3. `web/src/api/http.ts`: `BASES` (auth/asr/notification/note), `buildUrl`, `rawRequest` with single-flight refresh on 401, `deny:` → refresh+retry, `reauth_required` → `ReauthDialog`, `isConflict` (409/412). No tenant-mismatch handling. `CORS_CUSTOM_HEADERS` only for `auth`.
4. `web/src/shell/AppShell.tsx`: `.sb-head` wordmark; `WorkspaceSwitch` (`:183`) inside `AccountMenu`, hidden when `tenants.length < 2` (`:203`); `pick` navigates to `/` (`:211`). `SpacesNav.tsx` is personal folders.
5. `web/src/pages/settings/`: `SettingsLayout.tsx` groups Account / Workspace; `MembersSettingsPage.tsx` (`ROLES = member|admin`, "Add people" by e-mail, 404 → sign-up link copy); `WorkspaceSettingsPage.tsx`; `SharingStatsPage.tsx` at `/admin/sharing`.
6. `web/src/components/ShareDialog.tsx` (702 lines): sections Send / People with access / General access; `shareByEmail`, `unshareMember`, `setVisibility`, links; `shareWithMember` exported from `api/notes.ts` but unused. `pages/NoteEditorPage.tsx`: `editable = isDraft && !viewing` (`:1631`), 409 banner "Someone else saved a newer version" (`:1602`), `ShareDialog` mounted ~`:2296`. `pages/NotesPage.tsx` lists via `searchNotes({q, limit, cursor})`, no ownership filter. `api/asr.ts getResult` (`:107`) is called directly by the transcript tab.
7. `web/src/lib/errorCopy.ts` maps `not_a_member`, `membership_suspended`, `tenant_dissolved`, `no_workspace`, `legacy_session`, `personal_workspace`. `lib/storageKeys.ts`, `lib/captures.ts` (keys `notesai.capture.*`, not tenant-scoped). `components/Toaster.tsx`, `ConfirmDialog.tsx`, `Select.tsx`, `Segmented.tsx`, `Menu.tsx`, `AccessBadge.tsx` exist.
8. Existing tests to extend: `web/tests/authContext.test.tsx` (`stubFetch`), `shareDialog.test.tsx` (`server(routes)`), `workspaceSettings.test.tsx`, `emptyWorkspace.test.tsx`, `sessionGone.test.ts`, `transport.test.ts`, `signup.test.tsx`, `joinPage.test.tsx`.

## Rules for this sprint

`npm run typecheck`, `npm test`, `npm run build`, `npm run check:no-danger` after every task; `npm run test:e2e` at the end of phases 3 and 4 (`make web-e2e-stack` for the stack). No new dependencies without a line in the report (a `BroadcastChannel` is a browser API, not a dependency). No `localStorage` for anything the server owns; per-viewer conveniences only, wrapped in try/catch like `AppShell`'s sidebar flag. Every capability a role lacks is **absent**, never disabled (concept §6) — except where the server's reason is useful ("Leave" as last owner shows the reason). Strings are English literals as elsewhere; keep role words identical to iOS/macOS: Owner, Admin, Member, Viewer, Guest; can edit / can comment / can view.

---

## Phase 1 — Workspace identity and switching (needs W1 backend: `TokenResponse.tenant_id` on refresh, `me.active_membership`, `?ws=` deep links, `guest` role known)

### P1-1 Refresh/broadcast guard (`auth/AuthContext.tsx`, `api/http.ts`)
- `onRefreshed(login)`: `login.tenant_id !== activeTenantId` → `setWorkspaceMoved({to: login.tenant_id})`; `activeTenantId` unchanged.
- `rawRequest`: while `workspaceMoved` is set, any request to a non-`/auth/` path throws `WorkspaceMovedError` (no network). `useAuth()` exposes `workspaceMoved` and `adoptMovedWorkspace()` (= `setActiveTenantId(to)`, clear flag; `WorkspaceScope` remounts).
- `BroadcastChannel("notesai.workspace")`: `switchWorkspace` posts `{tenant_id}` after success; the listener in `AuthProvider` sets `workspaceMoved` in other tabs. Guard against the posting tab receiving its own message (compare to `activeTenantId`).
- `AppShell`: strip above the content — "This session switched to **{name}** in another tab." + button "Continue there" (`adoptMovedWorkspace`, `navigate("/")`). Name from `memberships` or `GET /tenants` cache.
- Tests (`authContext.test.tsx`): refresh with a different `tenant_id` → strip visible, `api()` rejects with `WorkspaceMovedError`, adopt clears; broadcast message → same; own message ignored.

### P1-2 Workspace header and switcher (`shell/AppShell.tsx`)
- `.sb-head` becomes `WorkspaceHeader`: name ("Personal" for `kind=personal`, with a house glyph), role label under it, caret; click opens `WorkspaceSwitch` (moved out of `AccountMenu`, always rendered). Collapsed sidebar: first letter in a circle, tooltip with the name.
- `WorkspaceSwitch`: personal first, then team, each with role; current one checked; footer "New workspace…" (phase 2; render disabled-with-tooltip "Coming in the next release" only until P2 lands — the one allowed disabled state, removed in phase 2).
- `AccountMenu` keeps account items only. `WorkspaceScope` unchanged.
- Tests: header shows "Personal" for a personal membership, the team name otherwise; one workspace → switcher still opens.

### P1-3 Workspace-scoped storage (`lib/captures.ts`, `lib/storageKeys.ts`)
- Keys `notesai.capture.{titles|mine|links|dismissed}` → `notesai.{tenantId}.capture.*`; one-time migration on first read moves legacy keys under the active tenant. `useCaptures` takes `activeTenantId` from `useAuth()`.
- Tests: migration runs once; two tenants do not see each other's capture bookkeeping.

### P1-4 Deep links with workspace (`App.tsx`, `pages/NoteEditorPage.tsx`, dictation/job pages)
- Read `?ws=`: if ≠ `activeTenantId` and a membership exists → `switchWorkspace(ws)` then load; no membership → `errorCopy.not_a_member` screen with the switcher. No `ws` + 404 → "Not in this workspace" empty state with "Switch workspace" (no cross-workspace probing).
- Tests: `ws` for a member switches then loads; for a non-member shows the copy.

### P1-5 Roles and copy (`pages/settings/MembersSettingsPage.tsx`, `api/types.ts`, `lib/errorCopy.ts`)
- `ROLES = member | admin | viewer`; role union gains `guest`; `errorCopy` gains `use_invitations`, `workspace_moved`, `insufficient_role`.

**Phase 1 acceptance:** two tabs cannot write into different workspaces (vitest + an e2e scenario in `regression.spec.ts` using two pages); the header always names the workspace; capture bookkeeping is per workspace; a `?ws=` link lands in the right workspace or explains why not.

---

## Phase 2 — Create, invite, manage (needs W2 backend: `/tenants` short form, `/tenants/{id}/invitations*`, `/auth/invitations*`, `/members/me`, `/dissolve`, `seat_meter`)

### P2-1 API (`api/tenants.ts`, `api/account.ts`, `api/types.ts`)
`createWorkspace(name)`, `listInvitations(tenantId, status)`, `invite(tenantId, {email, role, message, note_id?, note_role?})`, `resendInvitation`, `revokeInvitation`, `lookupInvitation(token)` (`auth:false`), `acceptInvitation(token)`, `myInvitations()`, `acceptMyInvitation(id)`, `declineMyInvitation(id)`, `leaveWorkspace(tenantId)`, `dissolveWorkspace(tenantId, confirmName)`; types `InvitationOut`, `InvitationLookup`, `SeatMeter`, `AcceptResult {tenant_id, role, token}`.

### P2-2 New workspace (`shell/AppShell.tsx`, `components/NewWorkspaceDialog.tsx`)
Dialog: name (1–80, Enter submits), "Create" → `createWorkspace` → `switchWorkspace(id)` → `/settings/members?first=1`. The members page with `first=1` shows an inline invite form and "You can do this later" link. Errors: 429 copy; 422 inline.

### P2-3 Members page (`pages/settings/MembersSettingsPage.tsx` rewrite)
- **Invite**: `components/EmailChips.tsx` (paste a list, Enter/comma/space separates, invalid chips marked), role `Select` (`member|admin|viewer`), optional message (≤ 500, counter), submit sends one `invite` per chip sequentially and reports per-address results (already a member / sent / failed). Copy under the form: "They'll get an e-mail from Notes AI. Nothing is shared until they accept."
- **In this workspace**: rows with avatar initial, name, e-mail, role `Select` (owners editable only by owners; last-owner rule shown as a tooltip from the server's 409), Remove (`ConfirmDialog`), "Left · {date}" badge for `left_at`.
- **Pending**: e-mail, role, "sent 2×", expiry, Resend, Revoke.
- **Seat meter**: "4 of 3 free seats" progress bar, link to Billing; never blocks.
- **Leave workspace** (everyone except on Personal): `ConfirmDialog`; 409 `last_owner` copy. After 204: adopt the returned token (`setAccessToken`, `setActiveTenantId(personal)`), `navigate("/")`, toast.
- **Danger zone** (owners, team only): Dissolve — type the exact name; 409 `has_other_members` copy ("Remove members first"). After 202: same adoption as leave.
- `reauth_required` is handled by `rawRequest` already; test that a 403 opens the dialog and the action completes.

### P2-4 Invite landing (`pages/InvitePage.tsx`, route `/invite/:token` outside `RequireAuth`; `pages/InvitationsPage.tsx`, route `/invitations` inside)
- `lookupInvitation` → card: "**{inviter}** invited you to **{workspace}** as {role}" (+ note title when `note_title`), masked e-mail. States: anonymous → "Continue with t•••@client.com" → `/login?next=/invite/:token` (the lookup returns only the masked address, so the login page asks for the full address and the server validates it on accept); signed in with matching address → "Join" → `acceptInvitation` → adopt token → `/` with the "You joined {workspace}" toast; signed in with another address → "You're signed in as x@y. Sign out and continue?" (logout then the anonymous state); 404 → one neutral screen.
- `/invitations`: list with Accept / Decline; `AccountMenu` shows a dot and "Invitations (n)" when `myInvitations()` is non-empty (fetched on shell mount and on window focus, cached 5 min).
- After an e-mail-code sign-up that auto-joined (`AuthResult.joined_tenant_ids`), show the toast on first render.

### P2-5 Tests
`membersSettings.test.tsx` (invite per chip, pending actions, leave/dissolve rules, reauth retry), `invitePage.test.tsx` (four states; accept adopts token), `newWorkspace.test.tsx`, `invitations.test.tsx`. e2e: `regression.spec.ts` gains "create workspace → invite → accept in a second context".

**Phase 2 acceptance:** create → switch → invite in one flow; an invite link in a fresh browser leads to sign-in and lands in the workspace; a mismatched session grants nothing; leave/dissolve adopt the personal workspace without a page reload.

---

## Phase 3 — Share by role, guests, comments, presence (needs W3 backend: `SharingView` v2, `/collaborators`, `/transcript-sharing`, `/comments`, `/presence`, `search?scope=`, `NoteEnvelope.my_level/can_read_transcript`)

### P3-1 API (`api/notes.ts`, `api/types.ts`)
`getSharing` v2 types (`people[]`, `pending[]`, `my_level`, `transcript_shared`, `workspace_kind`), `setCollaborator(noteId, sub, role)`, `removeCollaborator`, `shareNote(noteId, {email, role, message})` returning `{kind:"granted"} | NotAMember{can_invite}`, `setTranscriptSharing`, `listComments`, `createComment`, `editComment`, `resolveComment`, `unresolveComment`, `deleteComment`, `presenceHeartbeat`, `getPresence`, `searchNotes({scope})`.

### P3-2 Share dialog (`components/ShareDialog.tsx` rewrite)
Sections in this order:
1. **People** — `EmailChips` + role `Select` (`can view | can comment | can edit`) + message + "Share". Per address: member → granted; `not_a_member {can_invite}` → call `invite(tenantId, {email, role:"guest", note_id, note_role})` and show "Invited — they'll sign in to see this note"; `can_invite:false` (sharing policy) → the server's reason.
2. **Who has access** — one row per `people[]`: name/e-mail, source badge (Author · Guest · Everyone in the workspace), role `Select` where `can_change`, Remove. The "Everyone in the workspace · can edit / can comment" row appears when `visibility=workspace` and explains itself.
3. **Pending** — masked e-mail, note role, Revoke (calls `revokeInvitation`).
4. **General access** — `Segmented` `Private | Workspace` (hidden entirely when `workspace_kind=personal`), then the toggle "Include transcript and audio for viewers and commenters" with the line "Editors and workspace members always see them".
5. **Send a link** — unchanged recipient-link form (client links), last.
`initialFocus` prop keeps working (`people` / `client`).

### P3-3 Editor by level (`pages/NoteEditorPage.tsx`, `components/CommentsPanel.tsx`, `components/PresenceAvatars.tsx`)
- `editable = isDraft && (my_level === "manage" || my_level === "edit")`. For `comment`/`view`: body read-only (RichText in view mode), top strip "You can comment on this note" / "You can view this note", and the following are **absent**: Generate, item editing, the Share button, dictation, rename. Transcript tab absent when `!can_read_transcript`; `getResult` is not called.
- Conflict banner names who saved (`versions` → `created_by_display`) and offers "Reload latest" (existing) and "Copy my unsaved text" (clipboard) so nothing is lost.
- `PresenceAvatars` in the header: `getPresence` + `presenceHeartbeat` every 20 s while mounted and the tab is visible (`document.visibilityState`), stop on unmount.
- `CommentsPanel` (right side on ≥ 1024 px, sheet below on narrow): grouped by anchor (Note / section name / item text), "Resolved" filter, compose box at the bottom with the current anchor chip; "Comment…" entry in each section header menu and each item row's ⋯ menu sets the anchor; `anchor_present=false` rows show "on a removed line". Permissions from the API flags (`can_edit`, `can_resolve`, `can_delete`), never recomputed.

### P3-4 Notes list and shell (`pages/NotesPage.tsx`, `shell/AppShell.tsx`)
- `Segmented` All / Mine / Shared with me → `scope`; row chip with `my_level` via `AccessBadge` (extend: "Guest", "can comment").
- Guest mode (`activeRole === "guest"`): only "Shared with me" (no segmented control), no `NewMenu`, no `SpacesNav`, Settings shows Account only; `WorkspaceSwitch` labels the workspace "Guest in {name}".

### P3-5 Tests
`shareDialog.test.tsx` rewrite (grant, invite path, role change, transcript toggle, personal hides Workspace option), `noteEditorLevels.test.tsx` (each level's absent capabilities; transcript tab), `commentsPanel.test.tsx` (anchor compose, flags), `notesScope.test.tsx`, `guestShell.test.tsx`. e2e: `regression.spec.ts` "share as comment → second context cannot type, can comment"; `a11y.spec.ts` covers the share dialog and comments panel (keyboard path: Tab order chips → role → message → Share; Esc closes).

**Phase 3 acceptance:** every level renders the right surface with no disabled controls; a comment collaborator's keystrokes never reach `PUT /draft` (vitest asserts no call); transcript is not fetched when not allowed; guests see the reduced app; axe clean on the two new surfaces.

---

## Phase 4 — Organizations and GA polish (needs W4 backend; Part A only if the organization gate was met)

### P4-1 Organization pages (gated) (`pages/org/*`, `api/organizations.ts`)
- Settings › Workspace › "Organization" card: none → "Create an organization" (name + "attach this workspace") / pending proposal banner (Accept / Decline) / attached → link to the org.
- `/org/:id` with tabs: **Overview** (workspaces with attach state; "Attach a workspace" picker of the ones I own; detach with confirm), **Members** (directory grouped by person with per-workspace role chips; org role `Select` for org owners; "Enter workspace" for org admins with the break-glass confirm "This adds you as an admin; the owner is notified"), **Plan** (reuses the billing page component with the "managed by" header), **Policies** (sharing defaults + model defaults toggles; each shows "inherited by n workspaces" / "overridden in: …").
- `WorkspaceSwitch` groups workspaces under their org name; the workspace billing page shows "Pro (via {org})" and hides the plan controls.
- Hidden entirely when `MDX_ORGANIZATIONS_ENABLED` is off (the `GET /organizations` 404 drives it).

### P4-2 GA polish
- Remove the Keycloak-era login pieces the backend deleted (`/login/password` stays only if `credentials` is native; follow W4-1's final route list); remove `db_user` reads once W4-2 drops it.
- `lib/errorCopy.ts` complete for every code introduced in W1–W4; a test asserts each backend code in `docs/api/error-codes.md` with a `workspace`/`invitation`/`collab`/`org` prefix has copy.
- a11y pass (`a11y.spec.ts`) on members page, invite landing, share dialog, comments panel, org pages — zero serious/critical, light and dark.
- Analytics: client events (`workspace.switched`, `invite.sent{n}`, `invite.accepted`, `share.role_set{role}`, `comment.posted{anchor_kind}`, `scope.changed`) via the existing audit/metric path the app uses for `signup.*` (verify which — if none, do not invent a client-analytics pipeline; the server-side counters are the source of truth and this item is dropped with a note).

**Phase 4 acceptance:** org pages pass their vitest suites and axe; the switcher grouping is correct; no reference to removed backend routes remains (`npm run typecheck` + a grep test on `/admin/users/invite`, `db_user`).

---

## Security notes (client side)

Access tokens stay in memory; the refresh cookie is untouched. The invitation token appears only in the URL of `/invite/:token` and is never written to storage or logs (the `sessionStorage` `next` value stores the path — acceptable; clear it after use). `WorkspaceMovedError` is the only client-side control for tab drift; the server is still the authority. Capability hiding is UX, not security — every action still relies on the server's 403/404.

## Issues

| # | Title | Phase | Depends |
|---|---|---|---|
| WEB-1 | Refresh/broadcast workspace-move guard + strip | 1 | W1-4 contract |
| WEB-2 | Workspace header + always-on switcher | 1 | — |
| WEB-3 | Tenant-scoped capture storage | 1 | — |
| WEB-4 | `?ws=` deep links; not-in-this-workspace state | 1 | W1-6 |
| WEB-5 | Roles/copy alignment | 1 | — |
| WEB-6 | API module for workspaces/invitations | 2 | W2-3, W2-4, W2-5 |
| WEB-7 | New workspace dialog + first-invite flow | 2 | WEB-6 |
| WEB-8 | Members page rewrite (invite, pending, leave, dissolve, seat meter) | 2 | WEB-6 |
| WEB-9 | Invite landing + invitations list + auto-join toast | 2 | WEB-6 |
| WEB-10 | Sharing v2 + comments + presence API | 3 | W3-4, W3-7, W3-8 |
| WEB-11 | Share dialog rewrite | 3 | WEB-10 |
| WEB-12 | Editor by level, conflict banner, presence, comments panel | 3 | WEB-10 |
| WEB-13 | Notes list scopes + guest shell | 3 | WEB-10 |
| WEB-14 | e2e + a11y for phases 2–3 | 3 | WEB-8..13 |
| WEB-15 | (gated) Organization pages + switcher grouping | 4 | W4-8..10 |
| WEB-16 | GA polish: removed routes, error copy completeness, a11y, analytics decision | 4 | W4-1, W4-2 |

## Report back

Per phase: which backend contract version (OpenAPI snapshot hash) it was built against; tests added; any backend behaviour that differed from the sprint doc (file an issue against the backend sprint, do not work around it in the client); whether the analytics item in P4-2 was dropped; debt found (expected: no query cache makes the share dialog refetch `GET /sharing` after every change — acceptable; a `Toaster` queue for sequential invite results).
