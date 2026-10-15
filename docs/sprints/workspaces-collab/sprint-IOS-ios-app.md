# Sprint IOS — iOS app: workspaces, invitations, note collaboration

**Duration:** 4 phases of ~1 week each, in step with the backend sprints · **Team:** 1 Swift engineer (the same person may carry `sprint-MAC` when the two apps diverge little; budget 1.5 engineers for both)
**Depends on:** each phase starts when the matching backend contract is merged (W1 → phase 1, W2 → phase 2, W3 → phase 3, W4 → phase 4). Decoders and view models are built against the OpenAPI snapshot and the unit-test fixtures (`ios/Tests/NotesAICaptureTests/TestSupport.swift`), not against a live backend.
**Backend specs:** `sprint-W1…W4`. This document is the single source of truth for iOS work on this track.
**Concept:** `00-concept-workspaces-and-collaboration.md` §6.

## Sprint outcome

> On iPhone the workspace is always visible, a recording or an offline-typed note always lands in the workspace it was started in, a person can create a workspace and invite people from the avatar menu, an invitation link opens straight into joining, and a note can be shared by role from one sheet. Guests get a smaller app. Nothing a person typed is ever lost to a workspace switch or a network gap.

---

## Inspect first (stop and report if any is false on your branch)

1. `ios/CLAUDE.md`: build only, never launch a simulator; Xcode 16 synchronized folders (new files are picked up); `clients/Shared` is compiled into the module; run `scripts/check.sh` after every change; tests verified with `xcodebuild … build-for-testing`.
2. `AppState.swift` (`@MainActor ObservableObject`, ~1100 lines): `identity`, `memberships`, `tenantId`, `workspaces: [Workspace]`, `workspaceLost`, `switchingTo`, `sessionKind`, `sharingRules`; `refreshWorkspaces(force:)` (300 s cache), `switchWorkspace(to:)` (`:552-580`: `api.switchWorkspace` → `applyScope()` → clears path/spaces/search/notes/templates → reloads), `canSwitchWorkspace = sessionKind?.canGate`, `refreshNotes()` 403 → `refreshWorkspaces(force: true)`; `AppLink` with `invite(token)` ("cannot be opened yet") and `notes/<id>`.
3. `APIClient.swift` (actor, ~1400 lines): `BackendSettings` in UserDefaults; `X-Client-Type: ios`; single-flight `refresh()` with the refresh token in the body; `send(...)` 401 → refresh → retry, `reauth_required` → `reauthHandler` → retry, role denial → refresh → retry; `workspaces()`, `switchWorkspace(to:)` (`mintToken(activate:true)` + `store.rotateTenant`), `borrowToken(for:)` (`:448`), `currentTenant()`, `tenantMembers`, `addTenantMember`, sharing calls (`sharing`, `setVisibility`, `createPublicLink`, `createLink`, `sendLink`, `listLinks`, `revokeLink`, `shareWithMember`, `shareByEmail`, `sharingConstraints`); **no unshare call**.
4. `SessionStore.swift`: `KeychainSessionStorage` (service `ai.notes.capture.session`, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), `SessionRecord{token, gated, kind, refresh_expires_at, identity_id, email, last_tenant_id}`, `rotateTenant(tenantId:)`; optional Face ID gate.
5. `LocalStore.swift`: `StateScope{identityId, tenantId}`, keys suffixed `.<identity>.<tenant>`, `allScopes()`, `removeAll(for:)`. `PendingCaptures.swift`: audio + JSON sidecar with `identity_id`, `tenant_id`, `retarget(...)`. `clients/Shared/PendingMeetingNotes.swift`: offline-typed meeting notes with `identityId`, `tenantId`. `CaptureViewModel.syncPendingMeetingNotes()` (`:568`) filters by `identityId` only and uses the active token. No general offline edit queue; drafts go via `updateDraft(expectedVersion:)`; `NoteViewModel.editable` is `isDraft && viewing == nil` (`:247`); `NoteViewModel.write` sets `conflict = true` on 409 (`:1468`).
6. Views: `Views/WorkspaceView.swift` (`WorkspaceChip` shown when `workspaces.count > 1`, `WorkspacePicker` sheet), `Views/HomeView.swift` (`WorkspaceChip` at `:207`, avatar menu `accountItems()` ~`:274` with "Account & workspaces…", "Invite people…" gated by `canManageMembers`; `NoteRow.contextMenu` Private / Everyone in the workspace; `AccessPill`), `Views/InviteView.swift` (roles member/admin/viewer; 404 copy), `Views/AccountView.swift` ("Workspaces" group with Switch, `WorkspaceRoster`, sessions), `Views/NoteView.swift` ⋯ menu (`:180-225`: web link, copy link, workspace toggle, public link, Send by email, Share with client, PDF/Markdown), `Views/ShareEmailSheet.swift`, `Views/ShareWithClientSheet.swift`, `Views/NotificationsView.swift`, `Views/ReauthSheet.swift`, `Views/RootView.swift` (`.onOpenURL`, `scenePhase == .active` refreshes), `Views/SettingsView.swift`, `Views/Components.swift`, `Views/Dropdowns.swift`.
7. `Models.swift` (~2960 lines): `MembershipSummary`, `Workspace{…, myRole: String; title; roleLabel}` (`:284-291`), `SwitchedToken`, `MeResponse{identity, memberships}`, `SharingView` (`:1038`), `NoteSummary` (`:1686`, no author fields), `NoteAccess` (`:1729`), `Tenant{canManageMembers}` (`:2429-2445`), `TenantMember`. `AuthCopy.swift` has `legacy_session`, `no_workspace`, role-denial copy.
8. `ios/Support/Info.plist:50` registers the `notesai` scheme. Tests: `ios/Tests/NotesAICaptureTests/WorkspaceTests.swift` (scope isolation, switch publishes token, borrowed-token upload, `/tenants` decoding, `AppLink`), `PendingMeetingNoteTests.swift`, `SessionTests.swift`, `TransportTests.swift`.

## Rules for this sprint

`ios/scripts/check.sh` after every task (`--quick` for typecheck while iterating); `build-for-testing` for tests; never launch. Keychain only through `SessionStore`/`Keychain` (`clients/Shared/ConnectorStore.swift`); nothing new in the Keychain this track (invitation tokens are transient). Every file placed in `clients/Shared` must be byte-identical with macOS (`macos/CLAUDE.md`); when in doubt keep it per-app. Absent, not disabled, for capabilities a role lacks. Role words identical to web/macOS. Offline rule: nothing a person typed is lost — composed text survives a failed request in memory and is shown back for copying at minimum.

---

## Phase 1 — Workspace identity, correct-workspace writes (needs W1 backend)

### P1-1 Offline meeting notes land in their workspace (`CaptureViewModel.swift`)
- `syncPendingMeetingNotes()`: group `PendingMeetingNotes.all(identityId:)` by `tenantId`; for `tenantId == app.tenantId` use the session; otherwise `let bearer = try await api.borrowToken(for: tenantId)` and pass it to `startMeeting(…, bearer:)` (add the parameter the way `submitJob(... tenantId:)` already takes one). On `not_a_member`/`tenant_dissolved` for a borrowed tenant: keep the file, mark it `blocked(reason)` in the sidecar, and surface it in `PendingUploadsView` as "Workspace no longer available — Move to Personal / Delete" (reuse `PendingCaptures.retarget`).
- Tests (`WorkspaceTests.swift`): two pending notes in A and B with B active → `startMeeting` called with B's session for B and A's borrowed token for A; borrowed token refused → note kept, state `blocked`.

### P1-2 Workspace always visible; deep links (`Views/HomeView.swift`, `Views/WorkspaceView.swift`, `AppState.swift`)
- `WorkspaceChip` rendered with ≥ 1 workspace; "Personal" + house glyph for `kind == "personal"`; the picker lists personal first, role under each, checkmark on current; footer "New workspace…" (phase 2; until then not rendered at all — no disabled row).
- `AppLink.note(id, ws:)`: parse `?ws=`; if `ws != tenantId` and a membership exists → `switchWorkspace(to: ws)` then open; no membership → `linkNotice = AuthCopy.notAMember`. Without `ws`, a 404 shows "Not in this workspace" with a "Switch…" button opening the picker.
- `refreshNotes()`'s existing 403 handling stays; add the same to `loadNote(id:)`.
- Tests: `AppLink` parses `ws`; member → switch called; non-member → notice.

### P1-3 Roles and copy (`Models.swift`, `Views/InviteView.swift`, `AuthCopy.swift`)
- `Workspace.roleLabel` maps `guest` → "Guest"; `InviteView` offers `member | admin | viewer` (labels Member / Admin / Viewer); `AuthCopy` gains `insufficientRole`, `useInvitations`, `workspaceMoved` (the refresh path returns a different `tenant_id` than `store`'s `last_tenant_id` → adopt it through `applyScope()` and show a one-time banner "Switched to {name}" — on iOS one app = one session, so adopting is correct, unlike web tabs).
- Tests: decoding a `guest` membership; `roleLabel`.

**Phase 1 acceptance:** an offline note typed in A is created in A after switching to B (unit); the chip is visible with one workspace; `notesai://notes/<id>?ws=` switches for members; `check.sh` and the test target build.

---

## Phase 2 — Create, invite, join, manage (needs W2 backend)

### P2-1 API + models (`APIClient.swift`, `Models.swift`)
`createWorkspace(name:)`, `invitations(tenantId:status:)`, `invite(tenantId:email:role:message:noteId:noteRole:)`, `resendInvitation`, `revokeInvitation`, `lookupInvitation(token:)` (unauthenticated — add an `auth: false` path like the signup config call), `acceptInvitation(token:)` / `acceptInvitation(id:)` (both adopt the returned `TokenResponse` via the same path as `switchWorkspace`: `store.rotateTenant` + publish), `myInvitations()`, `declineInvitation(id:)`, `leaveWorkspace(tenantId:)` (adopt returned personal token), `dissolveWorkspace(tenantId:confirmName:)`, `tenantMembers` gains `left_at` and `seat_meter`. Models: `InvitationOut`, `InvitationLookup`, `SeatMeter`, `AcceptResult`. Error codes → `AuthCopy`: `already_member`, `invitation_email_mismatch`, `last_owner`, `has_other_members`, `confirm_name_mismatch`, `personal_workspace`.

### P2-2 New workspace (`Views/WorkspaceView.swift`, `Views/NewWorkspaceSheet.swift`)
Picker footer "New workspace…" → sheet (name field, Create) → `createWorkspace` → `switchWorkspace(to:)` → `HomeView` shows a one-time card "Invite your first teammate" → `InviteView`.

### P2-3 Invite + manage (`Views/InviteView.swift` rewrite, `Views/AccountView.swift`)
- **Invite** form: e-mail (multi-line paste accepted, split on separators), role picker, optional message; sends one `invite` per address; per-address result rows; copy "They'll get an e-mail from Notes AI. Nothing is shared until they accept."
- **Pending** list: masked address, role, "sent n×", expiry, Resend / Revoke (swipe actions).
- **Roster** (`WorkspaceRoster`): role menu (owner rows editable by owners only), Remove (confirmation), "Left · date" badge; seat meter line "4 of 3 free seats" (display only).
- `AccountView` per team workspace: "Leave workspace…" (confirmation; 409 `last_owner` copy); owners: "Dissolve workspace…" (type the name; 409 `has_other_members` copy). Both adopt the personal token on success and pop to `HomeView`.
- `reauth_required` → existing `ReauthSheet` through `reauthHandler`; test that the retry completes.

### P2-4 Invitation landing and inbox (`AppState.swift`, `Views/InviteLandingSheet.swift`, `Views/InvitationsView.swift`)
- `AppLink.invite(token)` → `lookupInvitation` → sheet: "{inviter} invited you to **{workspace}** as {role}" (+ note title). Signed out: "Sign in with t•••@client.com" → `SignInView` with the address field focused and a `pendingInviteToken` kept in `AppState` (memory only) → after sign-in `acceptInvitation(token:)` → adopt → `HomeView` with "You joined {workspace}" toast. Signed in, matching address: "Join". Mismatch: "Signed in as x@y — sign out to continue?" 404: neutral "This invitation is no longer valid".
- The mail's https link `{web}/invite/{token}` opens Safari; the web page shows "Open in the app" with the `notesai://invite/{token}` URL (web P2-4). Associated-domains universal links are **not** added (the web host is a runtime setting in `BackendSettings`).
- `InvitationsView` (from the picker row "Invitations (n)" and from a notification tap): Accept / Decline. `RootView` `.active` also refreshes `myInvitations()` (cached 300 s like workspaces). `NotificationsView` renders `workspace.invited` rows with a Join button.
- Auto-join at sign-up: `AuthResult.joined_tenant_ids` → toast on first `HomeView` render.

### P2-5 Tests
`WorkspaceTests.swift`: invite URL → lookup → accept adopts token and rotates `last_tenant_id`; create → switch; decoding of `InvitationOut`/`SeatMeter`; leave adopts personal; `pendingInviteToken` survives the sign-in round trip and is cleared after accept; a mismatch grants nothing.

**Phase 2 acceptance:** create → switch → invite from the phone; an invite deep link while signed out leads through sign-in to joining with no extra step; leave/dissolve land in Personal; all new error codes have copy.

---

## Phase 3 — Share by role, comments, presence, guests (needs W3 backend)

### P3-1 API + models
`sharing` v2 (`people`, `pending`, `myLevel`, `transcriptShared`, `workspaceKind`), `setCollaborator(noteId:sub:role:)`, `removeCollaborator`, `shareNote(noteId:email:role:message:)` → `.granted | .notAMember(canInvite:)`, `setTranscriptSharing`, comments CRUD, `presenceHeartbeat`, `presence`, `searchNotes(scope:)`; `NoteEnvelope.myLevel`, `canReadTranscript`; `NoteSummary.myLevel`, `collaboratorCount`. `clients/Shared/CollaborationModels.swift` only if byte-identical with macOS.

### P3-2 Share sheet (`Views/ShareSheet.swift` new; `Views/NoteView.swift`)
⋯ → "Share…" opens one sheet with sections: **People** (address field + role picker `Can view / Can comment / Can edit` + message + Share; `notAMember(canInvite: true)` → `invite(... role: "guest", noteId:, noteRole:)` → "Invited — they'll sign in to see this note"), **Who has access** (rows with source badge Author / Guest / Everyone in the workspace, role menu where `canChange`, swipe to remove), **Pending** (revoke), **General access** (`Private | Workspace` segmented; hidden in personal workspaces; "Include transcript and audio for viewers and commenters" toggle), **Send a link** (opens the existing `ShareWithClientSheet`). The old scattered menu items (workspace toggle, public link, send by email) move inside the sheet; "Copy link" and "Open in web app" stay in the menu.

### P3-3 Note by level (`Views/NoteView.swift`, `NoteViewModel.swift`, `Views/CommentsView.swift`, `Views/PresenceView.swift`)
- `canEdit = isDraft && (myLevel == "manage" || myLevel == "edit")` replaces the `viewing`-only rule; `comment`/`view` get a read-only body, a top strip ("You can comment on this note" / "You can view this note") and **no** Generate, item edit, dictation, rename, Share entries. Transcript tab absent when `!canReadTranscript`.
- Conflict: `conflict == true` → banner names who saved (`versions` → `createdByDisplay`), "Reload latest" and "Copy my text" (UIPasteboard) so the user's text is never lost.
- Presence: `PresenceView` avatars in the header; heartbeat every 20 s while the view is on screen and the scene is active; stop on disappear.
- Comments: "Comments (n)" toolbar button → `CommentsView` (grouped by anchor, Resolved filter, compose with anchor chip; "Comment…" in each section header menu and each item row's context menu sets the anchor). Offline/failed post: the text stays in the compose box with "Couldn't send — retry" (3 automatic retries with backoff), never dropped. Flags from the API decide edit/resolve/delete.

### P3-4 Home, filters, guest mode (`Views/HomeView.swift`, `Views/WorkspaceView.swift`, `Views/SettingsView.swift`)
- Filter chips All / Mine / Shared with me (`scope`); `AccessPill` gains "Guest", "Can comment", "Can view".
- Guest workspace (`activeWorkspace.myRole == "guest"`): no Record / New, no Spaces, filter fixed to Shared with me, Settings shows Account only; chip reads "Guest in {name}"; `NoteRow.contextMenu` has no visibility items.

### P3-5 Tests
`canEdit` per level; share sheet view-model (grant / invite path / transcript toggle / personal hides Workspace); comments compose retry keeps text; presence timer starts/stops with scene phase; guest hides capabilities; decoders.

**Phase 3 acceptance:** a comment collaborator cannot reach `updateDraft` (unit asserts no call); the transcript is not requested when not allowed; a failed comment post keeps the text; guests see the reduced app; `check.sh` green.

---

## Phase 4 — Organizations (read-only) and GA (needs W4 backend)

- (gated) `Workspace.organizationName` shown under the workspace in the picker and roster; `AccountView` shows "Plan: Pro (via {org})" and hides plan controls for attached workspaces; the attach-proposal notification deep-links to the web org page (`{web}/org/{id}`) — no native org management.
- GA: remove Keycloak-era code paths the backend deleted (password sign-in stays only if `credentials` is native; follow W4-1's route list), remove `db_user` decoding, make the `legacy_session` copy unreachable; `AuthCopy` completeness test against `docs/api/error-codes.md` prefixes; VoiceOver pass over the share sheet, comments and invite flows (labels on role menus, pills and swipe actions); analytics: none client-side unless the app already reports events (check `AppState` for a metrics path; if none, drop with a note).

**Phase 4 acceptance:** no dead code paths for removed routes; VoiceOver labels present on every new control; org labels render when present and are absent otherwise.

---

## Security notes (client side)

Invitation tokens live only in memory (`pendingInviteToken`) and in the URL that opened the app; never in UserDefaults or the Keychain. Borrowed tokens for pending notes are the existing contract (IDX-M2). Hiding capabilities is UX; every write still depends on the server's answer. Local scopes (`StateScope`) stay per `(identity, tenant)`; a guest workspace gets its own scope like any other.

## Issues

| # | Title | Phase | Depends |
|---|---|---|---|
| IOS-1 | Offline meeting notes by tenant with borrowed tokens; blocked state in Pending | 1 | W1-8 contract |
| IOS-2 | Chip always visible; `?ws=` deep links; not-in-this-workspace state; adopt moved session | 1 | W1-6 |
| IOS-3 | Roles/copy alignment | 1 | — |
| IOS-4 | API + models for workspaces/invitations | 2 | W2-3..5 |
| IOS-5 | New workspace sheet + first-invite card | 2 | IOS-4 |
| IOS-6 | InviteView rewrite (invite, pending, roster roles, seat meter); leave/dissolve | 2 | IOS-4 |
| IOS-7 | Invite landing sheet, inbox, sign-in hand-off, auto-join toast | 2 | IOS-4 |
| IOS-8 | Sharing v2 + comments + presence API/models | 3 | W3-4, W3-7, W3-8 |
| IOS-9 | ShareSheet | 3 | IOS-8 |
| IOS-10 | Note by level, conflict banner, presence, CommentsView | 3 | IOS-8 |
| IOS-11 | Home filters + guest mode | 3 | IOS-8 |
| IOS-12 | (gated) Org labels; GA cleanup; VoiceOver pass | 4 | W4-1, W4-2 |

## Report back

Per phase: the OpenAPI snapshot the decoders were written against; files added to `clients/Shared` (must list the macOS twin); any backend behaviour that differed (file against the backend sprint); whether the analytics item was dropped; debt found (expected: `AppState`/`APIClient` are per-app copies — the share/comments view models will be near-identical to macOS and are candidates for `clients/Shared` in a later cleanup).
