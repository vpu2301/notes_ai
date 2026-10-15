# Sprint W2 — Create a workspace, name it, invite anyone

**Duration:** 2 weeks · **Team:** 1 backend (auth-service), 1 web, 1 Swift (iOS + macOS), ½ floating (mail templates, tests, dashboard)
**Depends on:** W1 (dual/native mode on dev/staging, `guest` role known, rosters off `users`).
**Unblocks:** W3's "invite an outsider to a note" (same entity); W4 organizations (same invitation shape).
**Concept:** `00-concept-workspaces-and-collaboration.md` §3 (jobs 1–2), §5.
**Priority:** P0 for the track — this is the first thing a user *sees*.

## Sprint outcome

> From any client a person creates a workspace, names it, and invites people by e-mail with a role. Someone who already has an account sees the invitation in the app and in their inbox and joins with one tap; someone without an account gets a mail, signs up with that address and lands in the workspace they were invited to. Owners and admins see pending invitations, resend or revoke them, change roles, remove members; anyone can leave a workspace; an owner can dissolve an empty one. Nothing is granted without the invited address proving it is signed in.

**Demo:** web sidebar "Personal ▾ → New workspace…" → "Sunrise Studio" → Members → invite `tom@client.com` as member → Mailpit shows the mail → open the link in a private window → e-mail-code sign-up as Tom → lands in Sunrise Studio with a "You joined Sunrise Studio" banner → back as the owner: roster shows Tom, "Pending" is empty → iOS: avatar menu → "Invite people…" → `anna@acme.com` (has an account) → Anna's iPhone shows a notification "Invitation to Sunrise Studio" → Accept → the chip now lists it → Anna leaves → gone from both rosters.

---

## Inspect first (stop and report if any is false on your branch)

1. W1 landed: `MDX_IDP_MODE` is `dual` or `native` on dev; `GET /auth/me` returns `active_membership`; `POST /admin/users/invite` answers 410 in that mode.
2. `routers/tenants.py`: `POST /tenants` requires `tenant.create` + `requires_mfa()` and a 17-field `TenantCreate` body (`name`, `display_name`, `legal_name`, address…); `create_tenant` in `tenants_repository.py` sets neither `kind`, `plan` nor `signup_source` (defaults `team`/`legacy`/`admin`); `POST /tenants/{id}/members` requires `requires_mfa()` and resolves e-mail only to existing users (404 otherwise).
3. `auth_challenges.kind` CHECK includes `'invite'` (last recreated in `0032_be0_signup_verify.sql:24-28`; a widening migration drops **that** version) and no code opens that kind. `routers/native_common.py::recent_auth` is the step-up dependency (`reauth_required` → clients open the reauth dialog; web `api/http.ts`, iOS/macOS `APIClient.send`).
4. Native-mode mail goes through `domain/mailing.send_rendered` with templates `adapters/templates/<kind>.{en,de,uk}.html` (e.g. `auth_code`, `concierge_welcome`); keycloak-mode transactional mail is the `auth_mail_outbox` worker. Confirm which path `email_code_service` uses for `auth_code` and use the same one for invitations.
5. `email_code_service.verify` creates the identity + personal workspace for a new address (`is_new_identity`) and picks the landing workspace with `_preferred_membership(memberships, identity.last_tenant_id)` (`:631`).
6. `tenants_repository.count_active_owners(conn, tenant_id, exclude_sub)` exists; `remove_member` is a hard `DELETE`; `tenants.status` CHECK has `dissolved`; `IdentityRepository.sole_owner_tenants_with_members` (`:788`) exists for account deletion.
7. `libs/ratelimit` `FixedWindowLimiter(redis, prefix=…).allow(scope, subject, limit=, window_seconds=)`; auth-service prefix `mdx:auth:rl`.
8. Clients: web `WorkspaceSwitch` (`shell/AppShell.tsx`), `MembersSettingsPage.tsx`; iOS `Views/InviteView.swift`, `Views/AccountView.swift` ("Workspaces" group), `AppLink.invite(token)`; macOS `Views/Sidebar.swift` "Invite people…", `Views/WorkspaceViews.swift`, `AppURLRouter.swift` `invite/<token>`; `notesai` scheme registered in both `Info.plist`s.
9. `notification_events.Category` has no invitation category; `0011_notifications.sql` has a `category IN (…)` CHECK that later migrations did not widen — verify against the live schema (`\d notifications`).
10. Next free migration number; ADR next number (`0070` if W1 took `0069`).

---

## Scope

1. `tenant_invitations` table; routes to create, list, resend, revoke, look up (public, by token), accept.
2. `POST /tenants` simplified for self-serve: name only, `kind='team'`, `plan='free'`, `signup_source='self_serve'`, no MFA; the long form stays for admin onboarding.
3. Invitation mail (en/de/uk) and an in-app notification for invitees who already have an account.
4. Accept on web (`/invite/:token`), on iOS/macOS via `notesai://invite/<token>` and the universal web link; auto-accept at e-mail-code sign-up when the address matches.
5. Member management parity: roster with pending section, role change, remove, leave, dissolve (owner, team workspaces only, empty of other members) on all three clients.
6. Seat meter from `plan_limits.members` (display only).
7. Funnel instrumentation and a Grafana row.

## Explicit non-scope

- Per-note invitations and the `guest` role being offered (W3 — the `note_id` column exists from this sprint so W3 adds no migration to this table).
- Domain capture, join requests, invite links without an address ("anyone with the link joins") — NOT NOW (concept §9).
- Seat-limit enforcement, paid-plan gating of invitations.
- Transferring notes out of a workspace before dissolving it.
- Keycloak-mode invitations (`admin.py` stays 410 there too once W1's branch exists; the mode is being retired).
- Organization-level invitations (W4 reuses the entity with `organization_id`).

---

## G-1 Design decisions

**One invitation entity for every case.** `tenant_invitations(email, role, note_id NULL)` covers: existing account / none, workspace / note (W3). Acceptance is always authenticated and always checks `lower(identity.email) = invitation.email`; an invitation is never granted to whoever holds the link. **Rejected:** direct `add_member` for existing accounts without acceptance (silently putting someone into a workspace is the "spread like a virus" pattern the research warns about; also the invitee may not want this workspace on their switcher).

**The token is a capability only to *see* the invitation.** `GET /auth/invitations/{token}` (anonymous) returns workspace name, inviter display name, role and the (masked) address so the landing page can say "Sign in as t•••@client.com to join". Nothing else is readable with the token. Hash-only at rest (`sha256`, same rule as `auth_password_reset_tokens`, `0012_auth_recovery_and_mfa.sql:32`), 14-day expiry, single accept.

**Auto-accept at sign-up, explicit accept otherwise.** When `email_code_service.verify` creates a new identity and the address has open invitations, they are accepted in the same transaction and the landing workspace is the *invited* one (overrides `_preferred_membership`), because the person came from the mail. An existing identity accepts explicitly (in-app or via the link) — their switcher is theirs.

**Creating a workspace needs no step-up; managing people does.** `POST /tenants` (short form) runs on a plain authenticated session. Invite, role change, remove and dissolve use `recent_auth` (300 s window) in `dual`/`native`; clients already handle `reauth_required`. **Rejected:** keeping `requires_mfa()` on member management — MFA is optional for individuals (`MDX_REQUIRE_MFA` is a deployment setting) and would make a free team unable to invite anyone.

**Dissolve is soft and narrow.** Owner only, `kind='team'`, no other active members (remove them first — the UI says so), type the name. `status='dissolved'`, memberships set `suspended`, sessions in that tenant healed to personal on next refresh (existing `switch_tenant`/refresh path), 30-day restore via runbook (`UPDATE tenants SET status='active'`). Hard deletion of content is the existing retention/erasure machinery's job, not this sprint's. **Rejected:** dissolve with members (ownership transfer and "where did my notes go" need a design of their own).

**Leaving is `status='suspended'` on your own row, not a delete** — the roster shows "Left" for 30 days so an admin can re-invite without confusion, then the sweeper removes it. Owners cannot leave while they are the last owner (`count_active_owners`).

---

## Data model — migration `00NN_tenant_invitations.sql` (+ down)

```sql
CREATE TABLE tenant_invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT NOT NULL CHECK (email = lower(email) AND char_length(email) <= 320),
    role            TEXT NOT NULL CHECK (role IN ('admin','member','viewer','guest')),
    note_id         UUID,                                    -- W3: per-note invitation; NULL = workspace
    note_role       TEXT CHECK (note_role IN ('view','comment','edit')),
    invited_by      UUID NOT NULL REFERENCES identities(id) ON DELETE RESTRICT,
    token_hash      BYTEA NOT NULL UNIQUE,
    message         TEXT NOT NULL DEFAULT '' CHECK (char_length(message) <= 500),
    lang            TEXT NOT NULL DEFAULT 'en' CHECK (lang IN ('en','de','uk')),
    expires_at      TIMESTAMPTZ NOT NULL,
    sent_count      INTEGER NOT NULL DEFAULT 0,
    last_sent_at    TIMESTAMPTZ,
    accepted_at     TIMESTAMPTZ,
    accepted_by     UUID REFERENCES identities(id) ON DELETE SET NULL,
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenant_invitations_note_role_chk CHECK ((note_id IS NULL) = (note_role IS NULL)),
    CONSTRAINT tenant_invitations_window CHECK (expires_at > created_at)
);
-- One live invitation per (workspace, address, note)
CREATE UNIQUE INDEX tenant_invitations_live_idx
    ON tenant_invitations (tenant_id, email, COALESCE(note_id, '00000000-0000-0000-0000-000000000000'))
    WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX tenant_invitations_email_idx ON tenant_invitations (email) WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX tenant_invitations_tenant_idx ON tenant_invitations (tenant_id, created_at DESC);

ALTER TABLE tenant_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_invitations FORCE ROW LEVEL SECURITY;
GRANT SELECT ON tenant_invitations TO app_role;                       -- note-service (W3) lists a note's pending invites
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_invitations TO tenant_writer;
CREATE POLICY tenant_invitations_app_select ON tenant_invitations FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_invitations_writer_all ON tenant_invitations FOR ALL TO tenant_writer USING (true) WITH CHECK (true);
CREATE POLICY tenant_invitations_app_restrictive ON tenant_invitations AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- Memberships: a row a person left keeps a timestamp so the roster can say so.
ALTER TABLE tenant_memberships ADD COLUMN left_at TIMESTAMPTZ;
```

`tenants`: no change (`kind`, `plan`, `signup_source`, `plan_limits`, `status` exist). Backfill: none. Down: drop the table and the column. Add `tenant_invitations` to `_ENTITY_TABLES` (`app_role` select scope) and to `libs/db/tests/integration/test_rls_isolation_memberships.py` (writer path).

**Deletion:** note delete (W3) revokes its invitations; tenant dissolve revokes all; identity deletion (`request_deletion`) revokes invitations it sent (`invited_by`) and accepted rows keep `accepted_by NULL` via `ON DELETE SET NULL`. Expired/revoked rows older than 90 days are removed by a sweeper (`jobs/invitation_sweeper.py`, ADR-0041 runner, `GLOBAL_TENANT` pattern of the note-service sweepers). The address is PII: the DSAR erase runbook (`docs/runbooks/auth.md`) gains the table.

---

## API contract (auth-service; `routers/invitations.py` new, prefix `/tenants/{tenant_id}/invitations` for management and `/auth/invitations` for the invitee side)

Common: 404 for a tenant the caller is not a member of (no enumeration); all management routes `requires("tenant.manage_members","tenant")` + `_require_manager` (owner/admin) + `recent_auth` in dual/native; `_require_active_tenant` (the caller's `tid` must be this tenant — switch first, as `add_member` does today).

| Method | Path | Auth | Request | Response | Errors |
|---|---|---|---|---|---|
| POST | `/tenants/{id}/invitations` | manager, recent_auth | `{email, role: admin|member|viewer, message?, lang?}` | 201 `InvitationOut{id, email, role, status:"pending", expires_at, sent_count, invited_by_display, created_at}` | 422 invalid e-mail / role / `personal_workspace` (kind=personal); 409 `already_member`; 200 (not 409) when a live invitation exists → returns it and **resends** (idempotent re-invite); 429 |
| GET | `/tenants/{id}/invitations` | manager | `?status=pending|accepted|revoked|expired` (default pending) | 200 `{items:[InvitationOut]}` | |
| POST | `/tenants/{id}/invitations/{inv}/resend` | manager, recent_auth | — | 200 `InvitationOut` | 409 `not_pending`; 429 (≤ 3 sends / invitation / day) |
| DELETE | `/tenants/{id}/invitations/{inv}` | manager, recent_auth | — | 204 | 409 `not_pending` |
| GET | `/auth/invitations/{token}` | none (rate-limited per IP) | — | 200 `{workspace_name, inviter_display, role, email_masked, expires_at, note_title?}` | 404 for unknown / revoked / expired / accepted (same body) |
| POST | `/auth/invitations/{token}/accept` | authenticated | — | 200 `{tenant_id, role, token: TokenResponse}` — the session is switched to the new workspace (`switch_tenant(activate=True)`) and the new access token returned | 404 as above; 403 `invitation_email_mismatch` (signed-in address ≠ invited). An invitee who is already an active member gets 200 with the existing membership and the invitation marked accepted — joining twice is not an error |
| GET | `/auth/invitations` | authenticated | — | 200 `{items:[{id, workspace_name, inviter_display, role, expires_at, token_hint:null}]}` — the signed-in person's own open invitations (by `lower(identity.email)`), for the in-app "Invitations" list | |
| POST | `/auth/invitations/{id}/accept` | authenticated | — | as the token accept, for the in-app path (id is enough: the caller's e-mail is the proof) | 404; |
| POST | `/auth/invitations/{id}/decline` | authenticated | — | 204 (`revoked_at`, `revoked_by = self`) | |
| POST | `/tenants` | authenticated | **short form** `{name: 1–80 chars}` | 201 `TenantOut` (`kind=team`, `plan=free`, `signup_source=self_serve`, `plan_limits` = `MDX_SIGNUP_FREE_LIMITS`, slug auto + short random, locale/timezone from the identity) | 422; 429 (≤ 10 workspaces / identity / day); the long form (existing body) keeps working for admins |
| PATCH | `/tenants/{id}` | manager | `{display_name}` (existing route; `name` follows `display_name` for self-serve tenants) | existing | `personal_workspace` on status change (W1) |
| POST | `/tenants/{id}/dissolve` | owner, recent_auth | `{confirm_name}` | 202 `{status:"dissolved", restore_until}` | 409 `has_other_members`, 409 `personal_workspace`, 422 `confirm_name_mismatch` |
| DELETE | `/tenants/{id}/members/me` | member | — | 204 (`status='suspended'`, `left_at=now()`; session healed to personal on next refresh; the response also returns a fresh `TokenResponse` for the personal workspace so the client does not wait for the refresh) | 409 `last_owner` |
| GET | `/tenants/{id}/members` | existing | — | existing + `left_at`, profile from identities (W1), `seat_meter:{active, limit}` | |

`add_member` (`POST /tenants/{id}/members`) stays for `user_sub` (programmatic) and answers `409 use_invitations` when called with an `email` in dual/native.

**Invitation flow (`domain/invitation_service.py`, new):**

1. Validate; refuse `kind='personal'`; refuse an address that already holds an active membership (`already_member`); normalise e-mail; disposable-domain list is **not** applied (inviting a colleague on an odd domain must work).
2. Insert (or fetch the live row), token = 32 random bytes urlsafe, hash stored; `expires_at = now()+14d`.
3. Mail `invitation.{en,de,uk}.html` through the native mail path (same as `auth_code`): workspace name, inviter display, role in words, optional message rendered as text (never HTML), link `{web}/invite/{token}`, "expires in 14 days", "if you didn't expect this, ignore". If an identity with this address exists: also `notifications.emit(Category.WORKSPACE_INVITED, recipient hint = identity.id, payload = {tenant_id, invitation_id, role})` — no names in the payload; the renderer fetches the workspace name. Recipients outside the inviting tenant are the point here, so the notification-service recipient filter (`filter_to_tenant_members`) must allow `EXPLICIT_HINTS` of identities that are **not** members for this one category (see N-1).
4. Audit `tenant.invitation_created {role, has_account, note: bool}`; counters `mdx_auth_invitation_total{action, has_account}`.
5. Accept: in one `tenant_writer` transaction — re-read live row, e-mail match, `add_member(role, status='active', invited_by)` (or reactivate a `suspended/left` row), mark accepted, `switch_tenant(activate=True)`, audit `tenant.invitation_accepted`, `tenant.member_added {via:"invitation"}`; notification to the inviter `WORKSPACE_INVITATION_ACCEPTED` (in-app only).
6. Sign-up auto-accept: `email_code_service.verify` → after `create_with_personal_workspace`, `invitation_service.accept_all_open(identity)`; the first accepted team workspace becomes the landing `tid`; `AuthResult.joined_tenant_ids` lists them so the client can show "You joined …".

**Rate limits** (`FixedWindowLimiter`, prefix `mdx:auth:rl`): `invite:tenant` 50/day, `invite:identity` 100/day, `invite-lookup:ip` 60/min, `resend:invitation` 3/day, `tenant-create:identity` 10/day. Fail-open except `invite:*` (Level 3 — fail closed with 503, as the Sprint 22 send limiter does).

---

## notification-service

### N-1 Categories `workspace.invited` (in-app + e-mail IMMEDIATE — the e-mail is the auth-service invitation mail, so `email_mode=NONE` here to avoid two mails), `workspace.invitation_accepted` (in-app), `workspace.member_removed` (in-app, to the removed person, rendered in their personal workspace context). Catalog entries, templates, `ALLOWED_PAYLOAD_KEYS` (`tenant_id`, `invitation_id`, `role`, `workspace_name` is fetched by the renderer from `tenants` via the event's tenant — **not** carried). Widen the `notifications.category` CHECK in the same migration if the live schema still has it. Recipient rule: `EXPLICIT_HINTS` for `workspace.invited` skips `filter_to_tenant_members` (document why in `catalog.py`; test that no other category can). The notification row is written in the **invitee's personal tenant** (so it is visible wherever they are) with `payload.tenant_id` pointing at the inviting workspace; deep link `{base}/invitations`.

---

## Web (`web/`)

### W-1 API (`api/tenants.ts`, `api/account.ts`, `api/types.ts`)
`createWorkspace(name)`, `listInvitations(tenantId, status)`, `invite(tenantId, {email, role, message})`, `resendInvitation`, `revokeInvitation`, `lookupInvitation(token)`, `acceptInvitation(token)`, `myInvitations()`, `acceptMyInvitation(id)`, `declineMyInvitation(id)`, `leaveWorkspace(tenantId)`, `dissolveWorkspace(tenantId, confirmName)`; types `InvitationOut`, `InvitationLookup`, `SeatMeter`.

### W-2 Create + switch (`shell/AppShell.tsx`)
"New workspace…" at the bottom of `WorkspaceSwitch` → `NewWorkspaceDialog` (name; Enter creates) → `createWorkspace` → `switchWorkspace(id)` → `/settings/members?first=1` with an inline "Invite your first teammate" form. The switcher refreshes `listTenants()` after create/leave/dissolve (and on `workspace.*` notifications — reuse the notification WS subscription in `AppShell` if it exists; otherwise on focus).

### W-3 Members page (`pages/settings/MembersSettingsPage.tsx`)
Replace the "Add people" form with **Invite** (e-mail chips, role select `member|admin|viewer`, optional message, preview line "They'll get an e-mail from Notes AI; nothing is shared until they accept"). Sections: *In this workspace* (role select, Remove, "Left" badge with date), *Pending* (role, sent n×, Resend, Revoke, expiry), seat meter "4 of 3 free seats — upgrade soon" (display only, link to billing). Owners-only: *Danger zone* → Dissolve (type the name). Everyone: *Leave workspace* (disabled with reason when last owner). Error copy for every code above in `lib/errorCopy.ts`.

### W-4 Invite landing (`pages/InvitePage.tsx`, route `/invite/:token` outside `RequireAuth`)
`lookupInvitation` → card "Anna invited you to **Sunrise Studio** as a member" + masked e-mail. Anonymous: "Continue with t•••@client.com" → `/login?email=…&next=/invite/:token` (the e-mail field pre-filled, read-only when it came from an invitation); after sign-in, back here → `acceptInvitation` → adopt the returned token (`setAccessToken`, `setActiveTenantId`) → `/` with the "You joined …" banner. Signed in with another address: "You're signed in as x@y. Sign out and continue as t•••@client.com?" Expired/unknown: one neutral screen "This invitation is no longer valid. Ask the person who invited you for a new one."
`/invitations` (signed-in): list from `myInvitations()` with Accept / Decline; the account menu shows a dot when non-empty.

### W-5 Tests (vitest)
Members page: invite → pending row; 409 `already_member` copy; resend/revoke; leave disabled as last owner; dissolve requires the exact name. Invite page: anonymous → login redirect carries `next`; mismatch screen; accept adopts token and navigates. Switcher: "New workspace…" creates and switches.

---

## iOS (`ios/Sources/NotesAICapture/`)

- **`APIClient.swift`**: the W-1 endpoint set; `acceptInvitation(token:)` / `acceptInvitation(id:)` adopt the returned `TokenResponse` through the same path as `switchWorkspace` (`store.rotateTenant` + publish).
- **`Views/WorkspaceView.swift`**: `WorkspacePicker` gains "New workspace…" (sheet: name → create → switch) and, when `myInvitations` is non-empty, an "Invitations (n)" row → `InvitationsView` (Accept / Decline).
- **`Views/InviteView.swift`**: becomes the invite form (e-mail, role `member|admin|viewer`, message) + pending list with Resend/Revoke; roster rows get role change / Remove (manager) and a "Left" badge; "Leave workspace" in `AccountView` per workspace (not for Personal, not for the last owner — the server decides; the client shows the server's reason). Dissolve: `AccountView` → workspace → "Dissolve…" with name confirmation (owner only).
- **`AppState.swift` / `AppLink`**: `invite(token)` → `lookupInvitation` → `InviteLandingSheet` (same states as W-4; anonymous → sign-in with the address pre-filled → accept). Universal link `https://{web}/invite/{token}` is added to the associated domains entitlement **only if** the web host is known at build time (`BackendSettings.webAppURL` is runtime-configurable → keep the custom scheme as the reliable path; the mail carries the https link and the web page offers "Open in the app" with the `notesai://` URL on iOS/macOS user agents).
- **`Views/RootView.swift`**: on `scenePhase == .active` also refresh `myInvitations` (cheap; cached 300 s like workspaces).
- Tests: `WorkspaceTests.swift` — invite URL → lookup → accept adopts token; create → switch; decoding of `InvitationOut`.

## macOS (`macos/Sources/NotesAICapture/`)

Mirror iOS: `Views/Sidebar.swift` "New workspace…" + "Invitations (n)"; `Views/WorkspaceViews.swift` `WorkspaceList` gains create / leave / dissolve; `MainWindowView` `InviteView` sheet becomes the invite form + pending list; `AppURLRouter` `invite/<token>` → landing sheet; `App.swift` Apple-event path unchanged. Shared Swift (`clients/Shared/`) gets `InvitationModels.swift` only if byte-identical in both apps (`macos/CLAUDE.md` rule).

---

## Security review

- **Grant only to the proven address:** accept compares `lower(identity.email)` to `invitation.email`; the token alone reveals a workspace name, an inviter display name and a masked address — nothing else. Lookup is rate-limited per IP and answers one 404 shape for every non-live state.
- **Enumeration:** `POST /invitations` reveals `already_member` only to a manager of that workspace — acceptable (they see the roster anyway). Public lookup never says whether the address has an account.
- **Mail abuse:** per-tenant and per-identity daily caps, fail-closed; `message` is rendered as text; subject carries the workspace name only.
- **Cross-tenant:** management routes run under `tenant_connection(tenant_writer_pool, tenant_id)` after membership checks exactly like `add_member`; the invitee-side routes select by the caller's e-mail with `tenant_writer` and never by a client-supplied tenant id. `make test-isolation` walks the new id routes as tenant B (404 on A's invitation ids).
- **Step-up:** `recent_auth` on invite/role/remove/dissolve; the e2e proves a stale session gets `reauth_required` and completes after reauth.
- **Dissolve:** owner + typed name + no other members; sessions of the owner in that tenant heal to personal on the next refresh (existing path) — test it.
- **PII:** addresses live in `tenant_invitations.email` only; audit payloads carry `invitation_id`, `role`, `has_account`; logs carry ids; the sweeper and the DSAR runbook cover the table.

## Failure scenarios

| Failure | Behaviour |
|---|---|
| Mail relay down at invite | row is created, `sent_count=0`, response 201 with `delivery:"queued_failed"`; the pending list shows "Not sent — Resend"; alert on > 5/h |
| Accept races with revoke | conditional `UPDATE … WHERE accepted_at IS NULL AND revoked_at IS NULL` decides; loser gets 404 |
| Accept after the inviter lost manager rights | still valid (the invitation is the workspace's, not the inviter's); revoked only if the tenant is dissolved |
| Signup auto-accept fails for one invitation | identity + personal workspace are committed first (existing transaction); acceptances run in a second transaction per invitation; a failure leaves that invitation pending and logs `invitation.auto_accept_failed` |
| Client crashes after accept, before adopting the token | next refresh returns the new `tid` (the session was switched server-side) → W1's move handling adopts it |
| Redis down | limiters fail open except `invite:*` (503, retry copy) |

## Observability

Counters `mdx_auth_invitation_total{action=created|resent|revoked|accepted|declined|expired|auto_accepted, has_account}`, `mdx_auth_workspace_created_total{source}`, `mdx_auth_workspace_dissolved_total`, `mdx_auth_member_left_total`. Logs: `invitation_id`, `tenant_id`, `inviter_sub`, `result`. Grafana `workspaces.json`: created → first invite → accepted (by has-account) → first note opened by the invitee ≤ 24 h (join via `note.viewed_full` audit, nightly SQL `scripts/ops/workspace_funnel.sql`, same pattern as `loop_funnel.sql`). Alert: acceptance rate of no-account invitations < 20 % over 7 days (the mail or the landing page is broken).

## Tests

| Test | Expected |
|---|---|
| Invite new address | 201; row with hash; mail rendered with workspace name, no token in logs/audit |
| Invite existing identity | 201; notification row in the invitee's personal tenant; mail too |
| Invite active member | 409 `already_member` |
| Invite same address twice | second 200, `sent_count=2`, one row |
| Invite into personal workspace | 422 `personal_workspace` |
| Invite without recent auth | 403 `reauth_required` |
| Lookup valid / revoked / expired / accepted / unknown | 200 / 404 ×4 with identical bodies |
| Accept with matching e-mail | 200, membership active, session `tid` switched, audit kinds written |
| Accept with other e-mail | 403 `invitation_email_mismatch`, nothing changed |
| Accept twice | second 200, one membership |
| Sign-up with an open invitation | identity + personal + membership; landing `tid` = invited workspace; `joined_tenant_ids` set |
| Leave as last owner | 409 `last_owner` |
| Leave as member | 204; row suspended with `left_at`; refresh heals to personal |
| Dissolve with members / wrong name / personal | 409 / 422 / 409 |
| Dissolve valid | 202; `GET /tenants` omits it; owner's session heals |
| Short `POST /tenants` | 201 `kind=team plan=free signup_source=self_serve`; caller `owner`; 11th in a day → 429 |
| Tenant B on every new id route | 404 (`make test-isolation`) |
| RLS: `tenant_invitations` app_role scope | zero rows cross-tenant |
| Sweeper | rows expired > 90 days removed; live rows untouched |
| Web/iOS/macOS unit tests listed above | pass |

## Acceptance criteria (binary)

1. On all three clients a signed-in person can create a workspace by name and is switched into it within one screen.
2. An invitation to an address without an account results, after e-mail-code sign-up with that address, in an active membership with the invited role and the invited workspace as the landing workspace — without any further step.
3. An invitation to an existing account appears in that person's in-app invitation list and inbox within 60 s and is joinable with one action on each client.
4. An invitation link opened while signed in as a different address does not grant anything and shows the mismatch screen.
5. Invitations, role changes, removals and dissolves refuse without recent authentication and succeed after the reauth dialog on each client.
6. A member can leave; the last owner cannot; a dissolved workspace disappears from every member's switcher on their next refresh.
7. The seat meter shows `active / plan_limits.members` and never blocks an invite.
8. `make test-isolation` passes with the new routes; `tenant_invitations` is in the RLS entity list; `check-notification-pii-free` passes with the new categories.
9. `POST /admin/users/invite` answers 410 in dual/native; the web no longer references it.
10. ADR-0070 (invitations: one entity, authenticated accept, auto-accept at sign-up), runbook (`auth.md` § invitations: stuck/not-sent/erase), OpenAPI, changelog, dashboard committed; all CI gates pass.

## Implementation order

1. Migration + RLS + entity list → 2. `invitation_service` + repository + unit tests → 3. management routes + rate limits + mail templates → 4. invitee routes (lookup/accept/list/decline) + sign-up auto-accept → 5. short `POST /tenants`, leave, dissolve → 6. notification categories → 7. web W-1..W-5 → 8. iOS → 9. macOS → 10. e2e + isolation + funnel SQL + dashboard → 11. ADR/runbook/changelog.

## GitHub issues

| # | Title | Depends |
|---|---|---|
| W2-1 | Migration `tenant_invitations` (+ `left_at`), RLS, entity lists, sweeper | — |
| W2-2 | `invitation_service`: create/resend/revoke/accept/decline/auto-accept; token hashing; limits | W2-1 |
| W2-3 | Management routes + mail templates en/de/uk + audit kinds | W2-2 |
| W2-4 | Invitee routes; sign-up auto-accept; `AuthResult.joined_tenant_ids` | W2-2 |
| W2-5 | Short `POST /tenants`; `DELETE /members/me`; `POST /dissolve`; `add_member` 409 `use_invitations` | — |
| W2-6 | notification-service: `workspace.*` categories, cross-tenant hint rule, CHECK widening | W2-1 |
| W2-7 | Web: API, switcher create, members page, invite landing, invitations list, tests | W2-3, W2-4, W2-5 |
| W2-8 | iOS: create/invite/pending/leave/dissolve; invite deep link landing; tests | W2-3, W2-4, W2-5 |
| W2-9 | macOS: same | W2-3, W2-4, W2-5 |
| W2-10 | e2e (web + smoke-ios), funnel SQL, Grafana row, ADR-0070, runbook, changelog | all |

## Report back

State: migration number; the mail path used (outbox vs `send_rendered`) and why; whether the `notifications.category` CHECK needed widening; acceptance rate on the dev funnel after the e2e run (sanity: 100 %); any "Inspect first" fact that differed; debt found (expected: `tenants.name UNIQUE` collides with user-chosen names — the short form must suffix; `list_tenants_for_user` ordering by kind).
