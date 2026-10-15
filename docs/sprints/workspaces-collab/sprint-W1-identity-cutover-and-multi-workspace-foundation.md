# Sprint W1 — Identity cut-over and the multi-workspace foundation

**Duration:** 2 weeks · **Team:** 1 backend (auth-service, notification-service), 1 web, 1 Swift (iOS + macOS), 1 floating (infra, isolation suite, smoke)
**Depends on:** nothing new. Reuses the IDX track: `identities`, `tenant_memberships`, `auth_sessions.tenant_id`, `POST /auth/token` (`routers/session_native.py`), `SessionService.switch_tenant` (`domain/session_service.py:333`), `IdentityRepository.create_with_personal_workspace / ensure_personal_workspace` (`domain/identity_repository.py:358/470`), `public.profile_of_subs()` (0027), the three client switchers.
**Unblocks:** W2, W3.
**Concept:** `00-concept-workspaces-and-collaboration.md` §5–§6.
**Priority:** P0 — nothing in this track is real until a person can hold more than one workspace in a running deployment.

## Sprint outcome

> On dev and staging a person signs in with an e-mail code, lands in **Personal**, and can switch to any team workspace they belong to from the web sidebar, the iOS chip and the macOS menu. Every tab, in-flight upload, offline-typed note, notification socket and deep link follows the switch; a write never lands in a workspace other than the one shown. `GET /auth/me` describes the person by their memberships, not by a legacy home-tenant row. The demo tenants cannot reach production.

**Demo:** `MDX_IDP_MODE=dual` stack → web `/login` → code → "Personal" in the sidebar header → account menu → switch to "Acme Inc" → open a second tab → both show Acme → first tab switches back to Personal → second tab shows a "Workspace changed in another tab — reload" strip and never saves into Personal → macOS menu bar shows "Acme Inc ▾" → record offline on iOS in Acme, switch to Personal, reconnect → the note appears in Acme → `scripts/dev/workspace-smoke.sh` prints 0 wrong-workspace writes.

---

## Inspect first (stop and report if any is false on your branch)

1. `services/auth-service/src/auth_service/config.py` has `idp_mode: Literal["keycloak","dual","native"]` (`MDX_IDP_MODE`, default `keycloak`), and `main.py` mounts `session_native`, `email_code`, `account` only for `dual`/`native` (~`:202-236`).
2. `.env.example:128` says `MDX_IDP_MODE=keycloak`; `docker-compose.override.yml:125` passes it through with the same default; `infra/k8s/notes/values.yaml` and `values-prod.yaml` do not set it (so default `keycloak`).
3. `POST /auth/token` (`routers/session_native.py`, `TokenRequest{tenant_id, activate=True}`) → `SessionService.switch_tenant` updates `auth_sessions.tenant_id` and `identities.last_tenant_id` when `activate`; audit kind `auth.tenant_switched` exists in `docs/audit/event-kinds.md`.
4. `routers/me.py` returns `{claims, identity, memberships, db_user}`; `db_user` is read under `tenant_connection(state.app_pool, claims.tid)` from `users`, so it is `null` outside the identity's home tenant.
5. `tenants_repository.list_members` LEFT JOINs `users`; `resolve_sub_by_email` reads `users`. `routers/admin.py:57` `POST /admin/users/invite` creates a Keycloak user + `users` row only.
6. `identity_repository.py:48` `_PLATFORM_ROLES = {owner: (tenant_admin, member), admin: (tenant_admin, member), member: (member,), assistant: (member,), viewer: (viewer,)}`; `libs/auth/src/auth/perms.py` `KNOWN_ROLES` has no `guest`.
7. Web: `web/src/auth/AuthContext.tsx:181` `onRefreshed: (login) => scheduleRefresh(login.expires_in)` ignores `login.tenant_id`; `web/src/api/http.ts` has no tenant-mismatch handling; `TokenResponse` (`domain/transport.py:36`) carries `tenant_id` on every refresh.
8. Web switcher `web/src/shell/AppShell.tsx:182` (`WorkspaceSwitch`) is inside `AccountMenu`, rendered only when `tenants.length ≥ 2`; the sidebar head shows the wordmark, not the workspace name.
9. iOS `CaptureViewModel.syncPendingMeetingNotes()` (`ios/Sources/NotesAICapture/CaptureViewModel.swift:568`) filters pending meeting notes by `identityId` only and calls `startMeeting` with the active token; `clients/Shared/PendingMeetingNotes.swift` (the only shared file) stores `tenantId`. macOS has its **own copy** (`macos/Sources/NotesAICapture/CaptureViewModel.swift:614`), called from `AppState.loadWorkspaceData` (`:1133-1136`). iOS has `APIClient.borrowToken(for:)` (`:448`); macOS has `mintToken(for:activate:)` + the `borrowedTokens` cache (`APIClient.swift:36, 406-425`) instead.
10. notification-service `ws/handler.py:41` registers the socket by `user_id` only (`ws/registry.py::SocketRegistry.add(user_id, socket)` `:27`, `send_to_user(user_id, payload)` `:45`); the fan-out (`ws/handler.py:89-125`) delivers without comparing tenants; pub/sub channel pattern `mdx:notify:user:*` is built in `ws/fanout.py` (`_PATTERN` `:22`, `_publish` `:47-60`).
11. `infra/postgres/migrations/0013_seed_dev_tenants.sql` inserts tenants `…000a` (Acme Inc) and `…000b` (Globex Corp); `scripts/db/migrate.py` applies every `NNNN_*.sql` with no environment skip.
12. `infra/keycloak/realm-export.json` contains a `credentials` block with a plaintext `value` for user `notes-ai-owner`.
13. Web role picker `pages/settings/MembersSettingsPage.tsx` offers `member|admin`; iOS `Views/InviteView.swift` offers `member|admin|viewer`.
14. Next free migration number (`0071` if `dev` is at `0070_billing_interval`); next ADR number `0069` (`docs/adr/README.md` ends at 0058 in the index but code cites up to ADR-0068).

---

## Scope

1. Dev and staging run `MDX_IDP_MODE=dual`; other services' `AUTH_ISSUERS_JSON` include the native issuer; a scripted smoke covers sign-in, refresh, switch, logout, revoke on all three client transports. A gated flip to `native` at the end of the sprint.
2. Personal-workspace guarantee for every identity (backfill + CI check); "Personal" naming rule.
3. `GET /auth/me`, member roster, e-mail → identity lookups moved off `users`; `db_user` kept as a derived, deprecated field.
4. Four wrong-workspace defects fixed: web multi-tab drift, native offline meeting-note sync, notification socket fan-out, deep links without workspace.
5. Workspace identity visible everywhere: web sidebar header, macOS menu-bar popover, iOS chip always shown; the switcher is reachable with one workspace (it then shows "Personal" and, from W2, "New workspace…").
6. Role vocabulary: `guest` added to the schema CHECK, `KNOWN_ROLES`, `platform_roles_for` and the three clients' decoders (offered nowhere yet); `assistant` marked legacy; role pickers aligned to `member|admin|viewer`.
7. Demo seeds gated out of production; plaintext credential removed from the realm export.
8. Instrumentation for W2/W3 baselines: `share.blocked_no_account`, switch counters, wrong-workspace guard metric.

## Explicit non-scope

- Creating, renaming, dissolving workspaces; invitations; any new mail (W2).
- Per-note roles, guests being *offered*, comments, transcript gating (W3).
- Organizations (W4). The `native` flip in production (W4; there is no production yet, but the flip is still a separate decision).
- Making `calendar_connections` or MCP connectors workspace-independent (document the behaviour in the switcher copy; open a debt issue).
- Dropping `users` or `users.tenant_id` (W4 GA item; `make check-identity-bridge` keeps the bridge invariant until then).
- Web i18n beyond English strings.

---

## G-1 Design decisions

**Turn on the model that exists; do not build a third one.** ADR-0047 defined `dual` as a bounded migration state. W1 ends that boundedness on dev/staging by making `dual` the default there, and records the `native` flip as a gate. The Keycloak-era code paths (`login.py`, `password.py`, `signup.py`, `admin.py`) keep working in `dual`; nothing is deleted this sprint. **Rejected:** staying in `keycloak` and re-implementing switching on top of a Keycloak attribute — that is the single-tenant design the IDX track replaced.

**The session is the only carrier of the current workspace.** A client learns its workspace from sign-in or `POST /auth/token`, confirms it on every refresh (`TokenResponse.tenant_id`), and treats a mismatch as "the session moved" — never as "update my state silently". Web tabs share one session (cookie), so the rule is: the tab that switched wins; other tabs show a strip and reload on click. **Rejected:** per-tab sessions (would multiply `auth_sessions` rows per browser and break "sign out everywhere" expectations); storing `tid` in `localStorage` (a tab could then present a token for one workspace while believing it is in another).

**`users` becomes read-only derived data in this sprint, not deleted.** `me.db_user` is computed from the active membership (`role` = `admin.py::_primary_role` (`:33`; move it to `identity_repository.py` next to `platform_roles_for`) of `platform_roles_for(membership.role)`, `status` = membership status) so old clients keep parsing it; the roster and e-mail resolution read `identities` through `tenant_writer` (auth-service already holds that pool) — **not** by widening `app_role`'s grants (`make check-identity-grants` stays green). The W4 GA item drops the column and the bridge check.

**Personal is a kind, not a name.** `tenants.kind='personal'` rows are rendered as "Personal" by clients (with the e-mail underneath when another identity's data is on the device); `tenants.display_name` keeps whatever it is for API consumers. Backfill: every active identity without a `kind='personal'` membership gets one (`ensure_personal_workspace`), and `scripts/ci/check-identity-bridge.py` gains the assertion. **Rejected:** renaming rows (`"Tom's workspace"` is also the name self-serve signup wrote; a rename migration would race with users who already renamed).

**Tenant context in the notification socket is explicit.** The registry key becomes `(user_id, tenant_id)`; the fan-out delivers a frame only to sockets of the event's tenant. The pub/sub channel pattern is unchanged (`mdx:notify:user:*`, `ws/fanout.py`); the filter is applied by the subscriber that owns the socket. Redis changes: none beyond the frame carrying `tenant_id` (it already does in `NotificationEvent`).

**Demo seeds are a migration-time environment check.** `0013` stays applied where it already is (checksums); `scripts/db/migrate.py` gains `--skip-dev-seeds` driven by `MDX_ENV=prod` (k8s prod values) which skips files listed in `infra/postgres/migrations/DEV_ONLY` (one filename per line, starts with `0013_seed_dev_tenants.sql`), recording them in `schema_migrations` with `skipped=true` so numbering stays dense. Down migration of a skipped file is a no-op. **Rejected:** deleting the rows in a later migration (a prod DB that never had them would then diverge from staging in `schema_migrations`).

---

## Backend (auth-service)

### B-1 Mode flip + issuer config

- `.env.example`: `MDX_IDP_MODE=dual`; comment the three values. `docker-compose.override.yml`: default `dual`. `infra/k8s/notes/values.yaml` (staging): `MDX_IDP_MODE: dual`; `values-prod.yaml`: leave unset **and** add a `# W4` comment — `make check-k8s-rendered` must pass.
- Every service that verifies tokens gets the native issuer in `AUTH_ISSUERS_JSON` (`libs/auth/src/auth/issuers.py`); `make check-auth-issuer-config` is the gate. Document the pair of entries in `docs/runbooks/auth.md` § "Dual mode".
- `scripts/dev/workspace-smoke.sh` (new; `bash`, `curl`, `jq`): e-mail-code sign-in with `X-Client-Type: web` (cookie) and `macos` (body) → `GET /auth/me` → `GET /tenants` → `POST /auth/token {tenant_id: <team>}` → `GET /tenants/current` must return the team → refresh → `GET /auth/me.claims.tid` still the team → `POST /auth/token {activate:false}` for personal → the activated session is unchanged → logout → refresh is 401. Exit non-zero on any mismatch. Wire into `make smoke`.
- **Gate (task 10):** if the smoke, `tests/contract/test_token_contract.py`, `make test-isolation`, `web-e2e` and `smoke-ios` all pass against `dual`, run them once against `native`; if green, set `native` in `docker-compose.override.yml` and staging values and write that in the report. If anything fails, `dual` stays and the failures become the first W4 GA issue.

### B-2 Personal-workspace guarantee

- `ops/ensure_personal.py` (new CLI twin, ADR-0041 pattern): for every `identities` row with `status='active'` and no `tenant_memberships` row whose tenant has `kind='personal'`, call `IdentityRepository.ensure_personal_workspace`. Idempotent; prints counts; runs once per environment after deploy (`docs/runbooks/auth.md`).
- `scripts/ci/check-identity-bridge.py`: add "every active identity has exactly one personal membership with role `owner` and status `active`" and "no identity has two". Both run in `make check-identity-bridge`.
- `routers/tenants.py`: renaming a personal tenant through `PATCH /tenants/{id}` stays allowed (clients label it "Personal" regardless of `display_name`). Any change of `status` on a personal tenant is refused with the existing `personal_workspace` error code (already in `web/src/lib/errorCopy.ts`); emit it from `update_tenant`.

### B-3 `GET /auth/me` and rosters off `users`

- `routers/me.py`: build `db_user` from the active membership: `{sub, tenant_id: claims.tid, email, display_name (identity), role: _primary_role(set(platform_roles_for(m.role))), status: m.status, mfa_enrolled_at: identity.mfa_enabled ? identity.updated_at : null, last_login_at, created_at, mfa_reminder}`. Add top-level `active_membership: {tenant_id, name, kind, role, status}` and `personal_tenant_id`. In `keycloak` mode the old path stays (tests pin both).
- `tenants_repository.list_members`: `JOIN identities i ON i.id = m.user_sub` (connection is `tenant_writer`; it may read `identities`), return `email, display_name, status` from the identity; drop `platform_role` from the SQL and compute it. `resolve_sub_by_email` → `SELECT id FROM identities WHERE email = lower($1) AND status <> 'deleted'`.
- `routers/admin.py`: `POST /admin/users/invite` returns `410 gone {code:"use_invitations"}` in `dual`/`native` (W2 ships the replacement); `keycloak` mode unchanged. `PUT /admin/users/{sub}/roles` and deactivate/reactivate keep working on `users` in `keycloak` mode and act on `tenant_memberships` + session revocation (`state.denylist.revoke_sub(str(sub), ttl_seconds=settings.revoked_sub_ttl_seconds)`, as `admin.py:149` already does) in `dual`/`native` — smallest change: branch on `settings.idp_mode` inside the three handlers; the "never strip the last owner" guard uses `count_active_owners` (exists).
- `platform_roles_for`: add `"guest": ("guest",)`; `libs/auth/perms.py`: `KNOWN_ROLES += {"guest"}` with **no** ALLOW rows yet (a guest token can authenticate and reach nothing — W3 adds rows); `docs/auth/permissions.csv` gains the role with zero allowed rows; `test_perms` drift test passes.

### B-4 Migration `00NN_membership_roles_and_personal.sql` (+ down)

```sql
ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check
    CHECK (role IN ('owner','admin','member','viewer','guest','assistant'));   -- assistant: legacy, never offered
COMMENT ON COLUMN tenant_memberships.role IS 'owner|admin|member|viewer|guest; assistant is legacy (W1)';
COMMENT ON COLUMN tenants.kind IS 'personal: exactly one per identity, owner membership only, never dissolved (invariant enforced by ensure_personal_workspace + scripts/ci/check-identity-bridge.py)';
```
"One personal workspace per identity" cannot be a partial unique index (the predicate would need a subquery on `tenants.kind`), and duplicating `kind` onto the membership row is denormalisation that drifts. The invariant is enforced in code (`ensure_personal_workspace` already checks before inserting) and by the CI bridge check (B-2). Down: `UPDATE tenant_memberships SET role='viewer' WHERE role='guest'` (a no-op safety — W1 creates no guests), then restore the previous CHECK.

### B-5 Seeds and secrets

- `infra/postgres/migrations/DEV_ONLY` (new) listing `0013_seed_dev_tenants.sql`; `scripts/db/migrate.py`: `--skip-dev-seeds` / `MDX_ENV=prod` → record as `skipped`; `migrate-status` prints it; unit test in `scripts/db/tests/`.
- `infra/keycloak/realm-export.json`: remove the `credentials` array of `notes-ai-owner`; `make keycloak-test` must still pass (dev users keep theirs — they are dev-only; add a `make check-dev-keys`-style assertion that no user with a non-`dev-` username carries a credential value). Rotate the real password out of band (runbook note; not a code task).

### B-6 Metrics + audit

Counters: `mdx_auth_workspace_switch_total{result}`, `mdx_auth_personal_healed_total`, `mdx_auth_me_legacy_db_user_total` (how many callers still read `db_user` — the W4 drop gate). Audit: no new kinds (switching already audits). Logs: `tenant_id`, `session_id`, `result` — never e-mail.

---

## notification-service

### N-1 Tenant-aware socket registry

- `ws/registry.py::SocketRegistry`: `add(user_id, tenant_id, websocket)`, `sockets_for(user_id, tenant_id)`, `send_to_user(user_id, tenant_id, payload)`; `ws/handler.py:41` passes `claims.tid`; the fan-out (`ws/handler.py:89-125`, `ws/fanout.py`) passes the event's `tenant_id`. The unread count on connect is already tenant-scoped (RLS).
- Pub/sub subscriber: on a message for `user_id`, deliver to sockets whose `tenant_id` equals the frame's `tenant_id`; frames without one (none today — assert, log once) are dropped.
- Tests: new `services/notification-service/tests/unit/test_ws_registry.py` (the unit dir has only `test_alert_rules/catalog/preferences/render.py` today — follow `test_render.py`'s fixture style): two sockets for one user in tenants A and B; an A event reaches only A's socket; unread counts stay per tenant.
- Digest: unchanged (per `(day, tenant, user)` is correct — a person in two workspaces gets two digests; document in `docs/runbooks/notifications.md`). Deep links: `domain/render.py:216` adds `?ws={tenant_id}` to every `{base}/notes/{id}`, `/dictations/{id}`, `/asr/jobs/{id}` link (web W-4 consumes it).

---

## Web (`web/`)

### W-1 Refresh confirms the workspace (`auth/AuthContext.tsx`, `api/http.ts`)

- `onRefreshed(login)`: if `login.tenant_id !== activeTenantId` → set `workspaceMoved = {to: login.tenant_id}`; do **not** change `activeTenantId`; `rawRequest` refuses to send any non-`/auth/*` request while `workspaceMoved` is set (throws `WorkspaceMovedError`); `AppShell` shows the strip "This session switched to *Acme Inc* in another tab. Reload to continue there." with one button that calls `switchWorkspace(to)` semantics locally (`setActiveTenantId`, remount via `WorkspaceScope`).
- `BroadcastChannel("notesai.workspace")`: the tab that calls `switchWorkspace` posts `{tenant_id}` after `POST /auth/token` succeeds; other tabs enter the same `workspaceMoved` state immediately (no wait for their refresh timer).
- `WorkspaceSwitch.pick` (`shell/AppShell.tsx:211`) already calls `navigate("/")` after `switchWorkspace`; keep. Tests: `tests/authContext.test.tsx` — refresh returning another `tenant_id` blocks the next note request and shows the strip; a broadcast does the same; reload clears it.

### W-2 Workspace in the shell (`shell/AppShell.tsx`)

- `.sb-head`: workspace name (or "Personal") + kind badge for personal, as a button opening the existing `WorkspaceSwitch`; always rendered (one workspace → the menu lists it with a check and, after W2, "New workspace…"). Keep the wordmark small under it. Collapsed sidebar shows the first letter.
- `WorkspaceSwitch`: show `kind` ("Personal" first, as the server orders memberships), the role label, and the e-mail of the identity in the menu header.

### W-3 Workspace-scoped local storage (`lib/captures.ts`, `lib/storageKeys.ts`)

Prefix capture bookkeeping keys with `notesai.{tenantId}.…`; migrate existing keys once on boot into the active tenant's prefix (they could only have belonged to it). Per-note `DETAIL_KEY` is keyed by note id (globally unique) — leave.

### W-4 Deep links with workspace (`App.tsx`, `pages/NoteEditorPage.tsx`)

`/notes/:id?ws=<tenant_id>` (and `/dictations`, `/asr/jobs`): if `ws` ≠ `activeTenantId` and the user has that membership → `switchWorkspace(ws)` then open; if no membership → the existing error copy `not_a_member`. Without `ws`, a 404 on a note that `GET /tenants` shows another workspace could hold is **not** probed (no cross-workspace lookup; privacy) — show "Not in this workspace. Try switching." with the switcher.

### W-5 Roles

`MembersSettingsPage.tsx` `ROLES = member|admin|viewer`; `types.ts` role union gains `guest`; `errorCopy.ts` gains `use_invitations` ("Invitations are coming in the next release" — W2 replaces).

---

## iOS (`ios/Sources/NotesAICapture/`)

### I-1 Offline meeting notes land in their workspace

`CaptureViewModel.syncPendingMeetingNotes()`: group pending notes by `tenantId`; for the active tenant use the session token; for every other tenant `api.borrowToken(for: tenantId)` (exists, `activate:false`) and pass it to `startMeeting`; a `not_a_member` for a borrowed tenant leaves the file in place and surfaces it in Pending with "Workspace no longer available — move to Personal?" (reuses `PendingCaptures.retarget`). Test in `Tests/NotesAICaptureTests/WorkspaceTests.swift`: two pending notes in A and B, active B → `startMeeting` called with B's token for B and A's borrowed token for A.

### I-2 Chip always visible; deep links

`Views/HomeView.swift:207`: `WorkspaceChip` shown with ≥ 1 workspace ("Personal" with a house glyph for `kind=personal`). `AppLink`: `notes/<id>?ws=` → switch-if-member then open (mirror W-4); keep the `invite(token)` case saying "not supported yet" (W2).

### I-3 Roles

Roles are plain `String`s in `Models.swift` (`Workspace.myRole` `:291`, `TenantMember.role`), so nothing breaks on `guest`; add the label mapping ("Guest") in `Workspace.roleLabel` and the picker in `InviteView.swift` offers `member|admin|viewer`; `canManageMembers` (`:2445`) unchanged.

---

## macOS (`macos/Sources/NotesAICapture/`)

### M-1 Mirror I-1 in macOS's own `CaptureViewModel.syncPendingMeetingNotes()` (`:614`, called from `AppState.loadWorkspaceData` `:1133-1136`) using `mintToken(for: tenantId, activate: false)` / the `borrowedTokens` cache instead of iOS's `borrowToken(for:)`; and I-3.

### M-2 Menu-bar popover shows the workspace (`Views/RecentsView.swift`): a header row "Acme Inc ▾" opening the `WorkspaceList`; `App.swift`/`AppURLRouter.swift`: add the `notes/<id>` case (missing today) with `ws` handling; `refreshNotes()` gains the iOS-style 403 → `refreshWorkspaces(force:)` handling.

---

## Security review

- **Cross-tenant:** no new reader of other tenants' rows; `list_members`/`resolve_sub_by_email` run on `tenant_writer` inside `tenant_connection(tenant_id)` as today and return only identities that hold a membership in that tenant (add `AND EXISTS (SELECT 1 FROM tenant_memberships …)` to `resolve_sub_by_email` so an e-mail cannot be probed across the platform — the "no user with that email **in this tenant**" wording stays true).
- **Token/tab confusion:** the web rule (refuse requests after a detected move) is the control; test it.
- **Socket leak:** the fixed registry is a confidentiality fix — note it in `SECURITY.md`'s changelog section.
- **Seeds/credentials:** B-5.
- **Enumeration:** `GET /auth/me` exposes nothing new about other people.

## Failure scenarios

| Failure | Behaviour |
|---|---|
| `POST /auth/token` 5xx | client keeps the current workspace, shows a toast, no state change |
| Refresh returns a tenant the client never saw (membership added elsewhere) | same as a move: strip + reload |
| `ensure_personal_workspace` fails for one identity in the backfill | logged, counted, others continue; CI check fails until fixed |
| Redis down | notification sockets degrade as today; switching does not depend on Redis |
| Borrowed token refused (`not_a_member`) | pending note stays local, surfaced in Pending |

## Tests

| Test | Expected |
|---|---|
| Smoke script in `dual` for web + native transports | exit 0 |
| `GET /auth/me` outside the home tenant | `db_user` present, derived from the membership; `active_membership` set |
| `list_members` with a cross-tenant member | profile filled from `identities` |
| `resolve_sub_by_email` for an address with no membership here | `None` (404 upstream) |
| `platform_roles_for("guest")` | `["guest"]`; `perms.can("guest", "note.read", "note")` is `False` |
| Migration up/down | CHECK accepts `guest`; down restores |
| `migrate.py` with `MDX_ENV=prod` | `0013` recorded as skipped; no Acme row; staging run unchanged |
| realm export | no credential value outside `dev-*` users |
| WS: A/B sockets for one user | A's event only on A's socket |
| Web: refresh with other `tenant_id` | strip shown; note request refused; reload adopts |
| Web: broadcast from another tab | same strip |
| iOS/macOS: pending notes in two tenants | each created with its tenant's token |
| `make test-isolation`, RLS probes, `check-identity-bridge`, `check-identity-grants`, `check-auth-issuer-config` | pass |

## Acceptance criteria (binary)

1. On a `dual` stack the smoke script passes for web and native transports; `canSwitchWorkspaces` is `true` in the web app after an e-mail-code sign-in.
2. Every active identity on staging has exactly one personal membership (CI check green after the backfill run).
3. `GET /auth/me` for a user whose active workspace is not their home tenant returns a non-null `db_user` and `active_membership`.
4. Two web tabs cannot write into different workspaces of one session: the non-switching tab refuses writes until reloaded (vitest proves the refusal; the e2e `regression` suite gains a two-page scenario).
5. An offline meeting note typed in workspace A on iOS is created in A after the user switched to B.
6. A notification for workspace A is not delivered to a socket opened in workspace B (unit test).
7. `migrate.py up` with `MDX_ENV=prod` on an empty database produces no `tenants` row other than the platform tenant.
8. `infra/keycloak/realm-export.json` contains no plaintext credential for a non-dev user; `make keycloak-test` passes.
9. All role pickers offer `member|admin|viewer`; all clients decode `guest` without crashing (unit tests on the decoders).
10. ADR-0069 written (model shape, decision memo from the concept §11); `docs/runbooks/auth.md` § dual mode + backfill; OpenAPI regenerated; `CHANGELOG.md` entry; all CI gates in the README pass.

## Implementation order

1. B-5 seeds/credentials (small, unblocks safe staging) → 2. B-1 mode flip + issuers + smoke → 3. B-4 migration → 4. B-3 `me`/roster/roles → 5. B-2 backfill + CI → 6. N-1 → 7. W-1, W-2, W-3, W-4, W-5 → 8. I-1..I-3, M-1..M-2 → 9. isolation + e2e → 10. gate run against `native` → 11. ADR, runbook, changelog.

## GitHub issues

| # | Title | Depends |
|---|---|---|
| W1-1 | Dev-only migrations skipped in prod; realm export credential removed | — |
| W1-2 | `MDX_IDP_MODE=dual` on dev/staging; issuer config; `workspace-smoke.sh` | W1-1 |
| W1-3 | Migration: membership role CHECK (+guest, assistant legacy); `guest` in perms/`platform_roles_for` | — |
| W1-4 | `GET /auth/me` derived `db_user` + `active_membership`; roster + e-mail lookup via identities; admin invite 410 in dual/native | W1-3 |
| W1-5 | Personal-workspace backfill CLI + CI invariant | W1-2 |
| W1-6 | notification-service tenant-aware socket registry; deep links carry `ws` | — |
| W1-7 | Web: refresh/broadcast workspace-move guard; sidebar workspace header; scoped storage; `ws` deep links; roles | W1-4 |
| W1-8 | iOS/macOS: offline notes by tenant with borrowed tokens; chip/popover; `notes/<id>` on macOS; roles | W1-4 |
| W1-9 | Isolation + e2e additions; gate run on `native`; ADR-0069; runbook; changelog | all |

## Report back

State: migration number used; whether the `native` gate passed and what the compose/staging default now is; backfill counts (identities healed); the list of callers still reading `me.db_user` (from the counter after the e2e run); any "Inspect first" fact that differed; debt found (expected: calendar connections per workspace, MCP connectors device-wide, `tenant_of_sub()` still assuming one tenant, web i18n absent).
