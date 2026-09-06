# IDX-W2 — Web: account settings, workspace switcher, members & devices

**Status:** the A5/B1b half delivered (2026-09-05). **Three of the seven
issues were not built** — the workspace switcher, workspace settings and
members/invitations have no server to talk to. See §"Not built".
**Branch:** S01 (uncommitted working tree).

## The gate, stated first

W2 depends on **W1 and B1**. W1 landed. **B1 has never been run**, and
IDX-W1 already recorded the second half of the problem: `POST /auth/token`
does not exist either, because IDX-A2 delivered only `SessionService.start`.

Checked against the source, not assumed:

```
grep -rn invitation services libs infra/postgres web/src
  → one hit, an unrelated comment in web/src/components/ComingUp.tsx
```

`routers/tenants.py` serves exactly: `GET ""`, `GET /current`,
`GET|PATCH /{id}`, `POST ""`, `PUT|GET /{id}/logo`,
`GET|POST /{id}/members`, `PATCH|DELETE /{id}/members/{sub}`,
`POST /{id}/switch`. There is **no** `/leave`, **no**
`/transfer-ownership`, **no** `DELETE /tenants/{id}`, and **no**
`/invitations/*`.

So of §E's endpoint list: A5 and B1b are entirely present, and **every B1
line is absent**.

## Inspect first

### Web (§B)

| Item | Finding |
| --- | --- |
| `AppShell` | Sidebar: `sb-brand` (+ collapse toggle), `NewMenu`, `sb-nav` (`SideLink` + `SpacesNav`), `sb-spacer`, `sb-foot` (`ThemeSeg` / icon toggle when collapsed, then `AccountMenu`). `AccountMenu` had one item, "Sign out"; "Settings" was added above a separator. `TopBar` holds `NotificationBell`, which polls `notifApi.unreadCount()` on a 30 s interval. |
| Data fetching | Confirmed: every page calls `api()` into local `useState`. No query cache anywhere, so re-scoping really is "throw the tree away". |
| Reusable classes | `.card` / `.card.pad`, `.field` + `.label` + `.help`, `.row` / `.row-list`, `.btn` (`primary\|ghost\|danger`, `.sm`), `.banner banner-{danger,info,warn}`, `.modal-overlay/.modal/.modal-h/.modal-b/.modal-f`, `ConfirmDialog`, `useToast`, `Skeleton({width,height})` (**not** `rows`). |
| **Tabs** | `.tabs`/`.tab` already exist in `components.css` and are a **segmented pill**, not underline tabs — "the Mac has no underline tabs". The active class is **`on`**, not react-router's default `active`. The settings nav uses the existing pill via a `NavLink` render prop; the only new rule is `text-decoration: none`. |
| `.chk-row` | Already defined. The duplicate this sprint first wrote was removed. |
| Platform console | Re-confirmed: nothing in `web/` reads `GET /tenants`, and there is no `#/company` console here. |

### Server — §E line by line

| §E says | Reality |
| --- | --- |
| `/auth/mfa/totp/enroll\|confirm` | ✅ Step-up gated. Enrol returns `{enrollment_id, secret, otpauth_uri, expires_in}`; confirm returns `{recovery_codes}` **and ends every other session**. |
| `/auth/mfa/disable` | ✅ Step-up gated **and** needs a live factor in the body. Also ends other sessions. |
| `/auth/mfa/recovery/regenerate` | ⚠️ The path is **`POST /auth/mfa/recovery-codes`**. |
| `GET /auth/sessions`, `DELETE {sid}` | ✅ |
| `DELETE /auth/sessions?others=true` | ⚠️ The route is **`POST /auth/sessions/revoke-others`**, returns `{revoked}`. |
| `/auth/email/change/start\|confirm` | ✅ start is step-up gated; confirm returns the updated `IdentitySummary`. |
| `PUT\|DELETE /auth/password` | ❌ **Do not exist.** IDX-A4 was never run. `/auth/password/*` exists only under `MDX_IDP_MODE=keycloak` and writes to Keycloak's store. |
| `POST /auth/account/delete` | ✅ Step-up gated; body must be `{"confirm": "DELETE"}`; 202 `{purge_after, workspaces_dissolved}`; `409 sole_owner_with_members` carries `tenants[]`. |
| `PATCH /auth/me` | ✅ `{display_name?, locale?, timezone?}` → `IdentitySummary`. Not step-up gated, deliberately. |
| B1: `POST /tenants/{id}/leave`, `/transfer-ownership`, `DELETE /tenants/{id}`, all `/invitations/*` | ❌ **None exist.** |
| B1: `GET\|POST /tenants`, `GET\|PATCH /tenants/{id}`, `/members` | ⚠️ Exist, but as the **pre-IDX** routes: `MemberOut` is keyed on `user_sub`, `POST /members` resolves an email only **within that tenant's own `users` table** ("no user with that email in this tenant"), and both are gated on Keycloak-era `requires(...)` + `requires_mfa()`. This is member *management*, not invitation, and IDX-B2 replaces it. |
| B1b: `/tenants/{id}/devices` GET/POST/rotate/DELETE | ✅ All four, step-up gated. `CreatedOut {credential, secret}` and `RotatedOut {secret, old_expires_at}` are the only bodies that ever carry a secret. |

### The QR decision (§B asks for it on the record)

**`qrcode@1.5.4` (MIT) was added** and `QrCode.tsx` renders to inline SVG.
The alternative §B offers — manual key only — makes enrolment mean typing a
16-character base32 string into a phone, which is where people give up. The
package encodes locally at build time, so the provisioning URI never leaves
the browser; a hosted QR image service would mean mailing the shared secret
to a third party, and `web/README.md`'s CDN rule forbids it regardless.

Cost, measured: the JS bundle went **284.26 kB → 330.60 kB** (gzip
**88.47 → 103.70 kB**). The manual key is rendered beside the QR in groups
of four either way, and `QrCode` falls back to "use the key below" if
encoding ever throws — so the feature does not depend on the library
succeeding.

## What was built

| Issue | Delivered |
| --- | --- |
| W2-01 | `/settings/account`: profile name (`PATCH /auth/me`), email change (step-up → new address → code, reusing W1's `CodeInput`), delete account (typed `DELETE`, `sole_owner_with_members` renders the blocking workspaces). **Password card is informational** — see below. |
| W2-02 | `/settings/security`: full TOTP enrolment (QR + grouped manual key → confirm → recovery codes with a required acknowledgement), regenerate codes, disable (TOTP or recovery code), sessions list with "This browser" marker, per-session revoke (optimistic, rolled back on failure) and "Sign out everywhere else". |
| W2-03 | **Partial.** The `WorkspaceScope` remount boundary in `App.tsx` and the Settings entry in `AccountMenu`. No switcher — see §"Not built". |
| W2-06 | `/settings/devices`: list, create, rotate, revoke; `client_id` / `client_secret` / `token_url` revealed once through `SecretOnce`; personal workspaces get the explanation instead of a form. Tab hidden for non-managers, and the server re-checks. |
| W2-07 | Error map extended (`rotation_in_progress`, `personal_workspace` moved out of the test's exempt list); Vitest suite grown from 63 to **79** tests. |

### Files

New: `src/api/account.ts`, `src/components/{QrCode,SecretOnce}.tsx`,
`src/pages/settings/{SettingsLayout,AccountSettingsPage,SecuritySettingsPage,DevicesSettingsPage}.tsx`,
`tests/{secretOnce,securitySettings}.test.tsx`.

Changed: `src/api/types.ts`, `src/auth/AuthContext.tsx` (`refreshIdentity`),
`src/App.tsx`, `src/shell/AppShell.tsx`, `src/lib/errorCopy.ts`,
`src/styles/pages.css`, `tests/errorCopy.test.ts`, `package.json`.

### Three decisions worth naming

1. **No page reloads.** The first cut called `window.location.reload()`
   after enrolling, disabling and changing an email, because
   `identity.mfa_enabled` and `identity.email` had no other way to refresh.
   That throws away an unsaved note to update a boolean.
   `AuthContext.refreshIdentity()` replaced all three.
2. **Nothing here catches `403 reauth_required`.** Every step-up-gated call
   in `api/account.ts` is written as if the session were always fresh;
   `http.ts` opens the one dialog and replays the call. A call site that
   handled its own 403 would be a second, weaker step-up — which is exactly
   what §F warns against.
3. **`activeRole` gained a `db_user` fallback.** The Devices tab is shown to
   owners and admins, read from `memberships` — which `/auth/me` does not
   return yet, so on a plain page load the list is empty and a workspace
   owner would have looked like a stranger in their own workspace. The
   fallback reads the `users` row's role and lives in `AuthContext`, so
   `db_user` stays behind that one file for IDX-B2 to delete.

## Not built, and why

1. **W2-03, the workspace switcher.** `POST /auth/token` does not exist, and
   `POST /tenants/{id}/switch` explicitly does **not** re-scope the token —
   its own docstring says the SPA must "re-authenticate to obtain a token
   scoped to this tenant". A switcher built on it would change the
   highlighted name in the sidebar and leave every subsequent request
   carrying the old `tid`: not a partial feature but a misleading one, and
   the direct opposite of §H's "switching workspace never shows another
   workspace's notes". The **remount boundary was built** (`WorkspaceScope`
   in `App.tsx`, keyed on `activeTenantId`, covering `SpacesProvider`'s
   cache and `NotificationBell`'s poll), so when the endpoint lands the
   switcher is a list and one call.
2. **W2-04, workspace settings.** `PATCH /tenants/{id}` exists, but
   transfer-ownership, dissolve and the `personal → team` change — the three
   things the screen is *for* — do not. A branding form on its own was not
   worth a route.
3. **W2-05, members and invitations.** Invitations do not exist at all. The
   roster routes that do exist are the pre-IDX, `user_sub`-keyed ones that
   IDX-B2 removes, and their "invite by email" only finds people already in
   that tenant's `users` table. Building the screen twice was the worse
   trade; it waits for B1.
4. **The password card is informational.** §C asks for set/change/remove.
   `PUT`/`DELETE /auth/password` do not exist (A4 unrun), so the card states
   what is true for the account — "you sign in with an emailed code", or for
   a legacy account, where to change it — rather than offering a form that
   404s.
5. **Playwright suite and axe — not run.** Same as W1: `web/` has no browser
   harness, and §G's tests need the compose stack, a mail sink and a
   server-side clock stub for the step-up window. What could be asserted in
   jsdom was: enrolment shows the key once and the codes once, the codes
   screen will not close unacknowledged, `SecretOnce` writes to no storage
   and leaves nothing behind on unmount, the download is a page-built `Blob`,
   the current session offers no revoke button, an optimistic revoke rolls
   back, and a 404 from a Keycloak-mode deployment reads as an explanation.
6. **locale / timezone fields** — §I's own "cut first" item. `PATCH /auth/me`
   accepts them; there is no UI, because `web/` has no locale layer to
   change and the app renders times in the browser's zone already.

## Verification run here

- `npx tsc --noEmit` — clean.
- `npm test` — **79 passed**, 6 files.
- `npm run build` — clean; JS 330.71 kB (103.74 kB gzip), CSS 70.75 kB.
- `grep -rn "location.reload" src/` — none.

## Debt

- `AuthContext.memberships` is hydrated from the `AuthResult` at sign-in and
  from `/auth/me` when that endpoint grows the field. Until then a person
  who is added to a workspace mid-session sees it only after signing in
  again. Harmless while there is no switcher; a real bug the day there is.
- The devices screen reads `activeTenantId` from the token's `tid`. Once
  workspace switching works, it must re-fetch on the new tenant — the
  `WorkspaceScope` key already forces that, but it is untested.
- `docs/api/auth-service-openapi.json` is still stale (recorded in W1);
  §E's "regenerate DTOs from it" was therefore impossible, and the W2 DTOs
  are verified against `routers/{account,mfa_native,credentials,tenants}.py`.
- No eslint for `web/` (recorded in W1).
