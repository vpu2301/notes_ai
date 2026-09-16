# IDX-M2 — macOS: workspace context, pending uploads, offline & revocation

**Status:** delivered (2026-09-05) except the invitation deep link, which
has no server to talk to. The sprint carries `POST /auth/token` — the last
piece of IDX-A2 — because the switcher, the per-workspace uploads and the
whole revocation path rest on it.
**Branch:** S01 (uncommitted working tree).

## What the dependencies actually were

The pack depends on **M1** (delivered in the previous sprint) and **B1**.
Neither `POST /auth/token` nor B1 existed:

| §E says | Reality |
| --- | --- |
| `POST /auth/token` (A2) | ❌ Did not exist. The only `/token` was `POST /auth/oauth/token` (B1b, client credentials). `POST /tenants/{id}/switch` is an authorization gate and an audit hook — its own docstring says the client must "re-authenticate to obtain a token scoped to this tenant". **Carried here.** |
| `GET /invitations/{token}`, `POST …/accept`, `POST /tenants` (B1) | ❌ `grep -rn invitation services libs infra web/src` returns two unrelated string hits. No table, no routes, no mail. B1 has never been run — the same finding IDX-W1 recorded. `POST /tenants` exists but is the sprint-16 Keycloak-era onboarding route (`requires_mfa`, `requires("tenant.create")`). |
| `GET /tenants` | ✅ Exists, returns `{items: [{id, name, display_name, slug, status, is_active, logo_url, my_role}]}` — no `kind`, so "which of these is my personal workspace" comes from the memberships in `AuthResult`, not from this list. |
| `GET /auth/sessions`, `DELETE /auth/sessions/{sid}` | ✅ IDX-A5. |
| `DELETE /auth/sessions?others=true` | ❌ The route is **`POST /auth/sessions/revoke-others`**, and it is gated on recent auth — which is what M1's step-up plumbing was built for. |
| `PATCH /auth/me` | ✅ native mode only. |
| macOS URL handling | The app answers `notesai://` today, but never through the app: `ASWebAuthenticationSession` and a loopback listener intercept the OAuth and calendar callbacks first. A link clicked in a mail client had nothing to arrive at. |

The user was asked, before any code, whether to carry `/auth/token` only
or B1 as well, and chose `/auth/token`. So M2-05 is the one issue not
delivered, for the reason W1 gave when it declined to build `/invite/:token`
against an invented endpoint: a preview sheet built on a 404 is a screen
that renders and lies.

## Delivered — server (`POST /auth/token`, IDX-A2's last piece)

1. **`SessionService.switch_tenant`** — mints an access token for another
   of the identity's workspaces after re-reading the membership. Every
   refusal is a fact about the caller's standing and gets its own code:
   `not_a_member` (also the answer for a workspace that does not exist —
   whether it does is not the caller's business), `membership_suspended`,
   `tenant_dissolved`, `account_disabled`, `session_revoked`.
2. **`activate`** — `true` moves the session (`auth_sessions.tenant_id`,
   `identities.last_tenant_id`), which is what makes a switch outlive the
   access token that carried it and survive a relaunch. `false` borrows a
   token without moving anything: an upload that belongs to the workspace
   it started in must not move somebody's session out from under them.
3. **`IdentityRepository.membership_in`** — one query that distinguishes
   "suspended", "closed" and "never a member", which `list_memberships`
   deliberately cannot (it filters to live memberships in live tenants).
   Plus `set_last_tenant` and `SessionRepository.set_tenant`.
4. **`POST /auth/token`** in `routers/session_native.py` (native mode) —
   bearer-authenticated, returns **no refresh token and no cookie**
   (nothing rotated; a second credential for one session would be a replay
   waiting to happen), audits `auth.tenant_switched` with the payload the
   catalogue already specified (`sid`, `from_tenant_id`, `to_tenant_id`)
   and only when the session actually moved, and emits
   `mdx_auth_token_switch_total{result}` — the metric A2 named.
5. **Docs** — `docs/api/error-codes.md` gains `tenant_dissolved` and now
   says which router serves the `/auth/token` codes in which mode.

## Delivered — macOS

| Issue | Delivered |
| --- | --- |
| M2-01 | `LocalStore`: every per-person key is `<key>.<identity>.<tenant>`, with a one-time copy of the legacy `recentCaptures` under whoever signs in first (`localStateMigratedV2`; the legacy key is kept for one release). `knownIdentities` and `lastIdentity` make "whose data is on this Mac" answerable — and removable. |
| M2-02 | `APIClient.activateWorkspace` / `token(for:)` with a per-tenant token cache; `send(…, tenant:)` so any request can be made as another workspace; `AppState.switchWorkspace`, `workspaces`, `activeWorkspace`; the switcher in the sidebar account menu and in Settings › Account. The sidebar's account row now shows the **workspace** rather than the host — which company's notes these are is the thing you can be wrong about. |
| M2-03 | `PendingUploads`: send, send-to-another-workspace, export, delete (with a confirm that says it is the only copy), reveal in Finder. Shown on the home page above the notes, and on the sign-in screen (export/delete only) when a session has expired. Retried after sign-in and after reconnecting — never on a timer. |
| M2-04 | Revocation: a `not_a_member` / `membership_suspended` / `tenant_dissolved` answer marks the workspace, drops its cached token, moves to another membership (personal first) and says so in a banner; the lost workspace's local state stays on disk. Offline: M1's "Reconnecting…" for a live session; a session that hit its absolute expiry offline signs out but keeps identity, scope and pending recordings. |
| M2-05 | **Not delivered** (no server). The URL plumbing that was missing *is*: `AppURL.parse` and an `NSAppleEventManager` handler, because an `LSUIElement` app has no window for SwiftUI's `onOpenURL`. An `notesai://invite/<token>` link is recognised, the token is held in memory only (never written), and the app says the server does not support invitations yet. |
| M2-06 | Settings › Account: display name (`PATCH /auth/me`), workspaces, **where you are signed in** (`GET /auth/sessions`, End, Sign out everywhere else — the first real user of M1's step-up sheet), "Manage on the web" for password/2FA/email, and a sign-out that asks first when recordings are waiting. Settings › Advanced: remove another account's local data. |

### Three decisions worth stating

* **`PendingUploads` talks to a protocol, not to `AppState`.** The rules
  worth testing — send, keep, never delete without being asked — should
  not need an EventKit service, a Keychain and a live session to exercise.
  `PendingUploadsHost` is six members wide and `AppState` conforms to it.
* **"Read-only local mode" is the pending recordings, and says so.** The
  pack asks for a read-only mode when the refresh token expires offline.
  This app caches no notes locally — notes are read from the server on
  demand — so a browsing mode would render empty lists. What is genuinely
  local is the recordings that have not been sent, so those are what the
  signed-out screen shows, along with why the session ended.
* **A borrowed token being refused is not a sign-out.** A 401 on a
  workspace-scoped request drops that workspace's token and retries; a
  second 401 refuses the request and leaves the session alone. Only the
  active session's own 401 can end it.

## Verification run here

**Against the dev stack** (`MDX_IDP_MODE=native`, restored to `keycloak`
afterwards), with a fresh identity given a second workspace directly in
the database (B1's job in the product):

* `GET /tenants` → `[("…'s workspace", owner), ("M2 Team", admin)]`;
* `POST /auth/token {activate: true}` → roles `[tenant_admin]` from the new
  membership, `tid` changed, **`sid` unchanged**, `refresh_token: null`,
  no `Set-Cookie`;
* the next `POST /auth/refresh` came back in the team workspace — the
  session moved, so a relaunch lands there;
* `{activate: false}` for the personal workspace minted its token while
  `auth_sessions.tenant_id` stayed on the team workspace;
* membership suspended → `403 membership_suspended`; membership deleted →
  `403 not_a_member`; `tenants.is_active = false` → `403 tenant_dissolved`;
* audit: `auth.login` → `auth.tenant_switched` → `auth.refresh`.

**Suites:** auth-service unit **341 passed** (11 new for `/auth/token`);
macOS `swift test` **62 passed** (24 new); `ruff check`, `ruff format
--check`, `mypy --strict` on the changed modules, `make check-rls`,
`check-identity-grants`, `check-metric-names`, `check-alert-rules`,
`lint-imports` green. `make openapi-check` fails on the pre-existing
note-service drift (verified against a stashed tree during IDX-M1).

## Acceptance criteria

| Criterion | State |
| --- | --- |
| Local state separated by identity and tenant; a test switches workspace and asserts A's meetings are not visible while B is active | Met — `LocalStoreTests` (two workspaces, two identities, and the bounded list). |
| No scenario in §H deletes a not-yet-uploaded recording without explicit user action | Met — the only `remove` calls are the confirmed Delete, the account-data removal, and a server-confirmed upload. `PendingUploadsTests` asserts the file survives a 503, a lost membership and an offline pass. |
| A user removed from a workspace while offline loses no local content and is moved to another workspace on reconnect | Met — `noteWorkspaceLoss` → personal workspace first; the lost workspace's keys stay on disk. |
| Invitation deep links work in all three sign-in states | **Not met** — no invitation server exists (B1). The link is received and answered honestly. |
| MAC-S1's queue rows carry `identity_id`/`tenant_id` | Not applicable — MAC-S1 has not shipped. The contract it must honour is below. |

## Not met / next

1. **M2-05, the invitation flow.** Needs B1: an invitations table, a
   create/revoke surface, the mail, `GET /invitations/{token}` and
   `POST /invitations/{token}/accept`. The client-side seam is in place
   (`AppURL.invite`, the token held in memory, the main window brought
   forward), so the sheet is the only missing piece once a server exists.
2. **Creating a workspace from the Mac.** `POST /tenants` is the Keycloak
   -era route and is not mounted in native mode; the switcher lists what
   you are already in.
3. **`GET /auth/me` still answers `{claims, db_user}`.** `hydrateIdentity`
   is wired and is a no-op until IDX-B2 extends it; the workspace list
   comes from `GET /tenants` instead, which is what M2 §D's "membership
   refresh" actually needs.
4. **A meeting uploaded into a workspace you are not looking at gets no
   live status updates** — the recent is filed under that workspace's key
   and polled there; switching to it and refreshing picks the status up.
   Worth revisiting if per-workspace background polling ever earns its
   keep.

## The contract MAC-S1 must honour

If the Foundation pack's chunked-capture / resumable-upload queue ships,
it replaces `pending/` — and it inherits these rules, which is the whole
reason this section exists:

* every row carries `identity_id` **and** `tenant_id`, written when the
  recording starts, not when the upload does;
* no row is ever deleted because an upload failed, a membership vanished
  or a session ended — only after the server confirms it has the audio, or
  because the person asked;
* a row whose workspace is gone is offered to another workspace or
  exported, never silently retried into whichever workspace happens to be
  active;
* its tests include the "membership removed" case, because that is the one
  that looks like a bug in the queue and is actually a change in the
  world.

## Debt

* **`recentCaptures` legacy key.** Copied, not moved, for one release.
  Delete `Keys.recents` (the unscoped one) in the next macOS sprint —
  after which `localStateMigratedV2` can go too.
* **`updateRecent` is scoped to the active workspace**, so a job finishing
  in another one does not get its status written until the person goes
  back. Harmless today; it would matter if the meetings list ever became
  cross-workspace.
* **The Mac still cannot create a workspace or invite anyone into one.**
  `InviteView` adds an existing account to the current workspace via
  `POST /tenants/{id}/members`; that is B1's to replace.
* **iOS.** `ios/` is still a file-for-file copy of the pre-M1 client: one
  bucket of local state, a cookie session, no workspace context. IDX-I1
  will repeat both sprints unless the two apps are given a shared package
  first — the recommendation stands from M1's debt list, and has now
  doubled in size.
