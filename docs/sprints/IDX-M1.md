# IDX-M1 — macOS: Keychain sessions, bearer transport & sign-in flows

**Status:** delivered (2026-09-05), and the sprint carries the server half it
turned out to depend on. A brand-new address signs up from the Mac, gets a
session in the Keychain, rotates it, replays it (and is signed out for
security), and signs out — end to end against the dev stack.
**Branch:** S01 (uncommitted working tree).

## The finding that reshaped this sprint

The pack's dependency line reads *"Depends on: A5"*, and A5's own "Not
delivered" section is the reason that does not hold:

> The rest of IDX-A2's session surface: `refresh`, `logout`, `/auth/token`,
> the `/auth/me` extension. Sessions are created, listed and revoked;
> **nothing rotates them.**

Concretely, before this sprint:

* `SessionService` had one method, `start` (IDX-A3 carried it); `refresh`,
  `switch_tenant` and `revoke` were never written, and neither was
  `routers/session_native.py`.
* `POST /auth/refresh` and `POST /auth/logout` were `routers/login.py`'s,
  Keycloak-backed **in both modes**, and both read the **cookie only**.
  Neither accepts `{refresh_token}` in a body.
* `POST /auth/login` returns the pre-IDX `LoginResponse` — no
  `refresh_token` field, ever, for any client type.

So the one thing M1 exists for — a refresh token in the Keychain that
survives a restart — had nothing to talk to. `X-Client-Type: macos` would
have earned the app a refresh token from `/auth/email/verify`
(`domain/transport.py` does gate that correctly), and nothing in the estate
could rotate or revoke it: the session would die at the first access-token
expiry, fifteen minutes in, and no client work could lift that.

The user was asked before any code was written, and chose to carry the
minimum A2 slice rather than ship a client against a ceiling. That is the
same call IDX-A3 made when it carried A1's tables and A2's
`SessionService.start`, and it is why this document has a server half.

## B. Inspect first — what was actually there

### macOS (the pack's §B, corrected)

| Item | Finding |
| --- | --- |
| `APIClient` | As described: `URLSessionConfiguration.default` with `httpCookieStorage = .shared`, proactive refresh under 30 s, 401 → single-flight `refresh()` → one retry, second 401 → `sessionLost()`. `send(...)` also has an MFA arm: a 401 whose problem mentions `mfa`/`otp` is re-thrown rather than refreshed, because `POST /tenants/{id}/members` uses 401 to ask for a code. Kept. |
| `scheduleKeepAlive` | Refreshes at `expires_in − 60` s, floor 10 s, and re-arms itself at 90 s on a transient failure. Removed — its whole reason was Keycloak's 30-minute idle session. |
| `AppState` | As described. `signIn(email:password:otp:)` was the only way in; `sessionExpired()` took no reason, so every sign-out looked the same on the sign-in screen. |
| `Connectors/ConnectorStore.swift › enum Keychain` | `read/write/delete(account:)` over one hard-coded service, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, and **`write` discards its `OSStatus`**. Extended (service parameter, status returned, `kSecAttrSynchronizable: false`), not duplicated. |
| `CaptureViewModel.process` | `defer { try? FileManager.default.removeItem(at: fileURL) }` — deletes on every exit, including `.failed` and cancellation. This is the line the pack calls a "capture-safety fix"; it is the one change here that can prevent an unrecoverable loss. |
| `SignInView` | Email + password + optional OTP, one card. **`BackendSettings.forHost` and `pointsAtLocalhost` do not exist on macOS** — they are the iOS app's (`ios/Sources/NotesAICapture/Models.swift:21,82`). The macOS "Server…" affordance is the host name under the card, which now expands into the four URL fields. |
| Design components | `DSTextField`, `DSLabel`, `DSButtonStyle`, `DSNotice`, `DSDivider`, `DSWordmark`, `dsCard` — all as described. No six-box code field existed; one was added (`DSCodeField`). |
| Tests | **None.** No test target in `Package.swift`, no `Tests/` directory, and no macOS job in `.github/workflows/ci.yml` — every job is `ubuntu-latest`. The Swift half of the estate had never been compiled by CI. |

### Server — what §G's endpoints actually were

| §G says | Reality before this sprint |
| --- | --- |
| `POST /auth/refresh` (body) | Cookie-only, Keycloak-backed, mounted in both modes. **Written here.** |
| `POST /auth/logout` (body) | Same. **Written here.** |
| `POST /auth/email/start\|verify` | ✅ native mode only; `verify` already returns the refresh token in the body for `X-Client-Type: macos`. |
| `POST /auth/mfa/verify` | ✅ `routers/mfa_native.py`; `method ∈ totp \| recovery_code`. |
| `POST /auth/login` | ✅ but Keycloak-backed and never returns a `refresh_token`. Native mode has no password grant at all (IDX-A4). |
| `GET /auth/me` | ✅ but **not extended** — still `{claims, db_user}`, no `identity`, no `memberships` (IDX-B2's). |
| `PATCH /auth/me` | ✅ `routers/account.py`, native only. |
| `POST /auth/reauth` | ✅ 204, `{method, code, challenge_id?}`. |
| `POST /auth/reauth/email/start` | ❌ The route is **`POST /auth/reauth/start`**: no body, bearer required, and the **server** decides the methods. |
| Error code `reauthentication_required` | ❌ It is **`reauth_required`** (`docs/api/error-codes.md:31`), and the extras carry `reauth_window_seconds`, not `methods`. |
| `AuthResult` discriminator | Not `kind`; it is **`status: "authenticated" \| "mfa_required"`**, with the token fields defaulted so an `mfa_required` result is a real 200. |

## Delivered — server (IDX-A2's remaining session half)

1. **Migration `0030_idx_session_rotation`** — `auth_sessions.previous_refresh_token_hash`
   + `rotated_at`, a unique partial index on the previous hash, and two new
   values for 0025's `revoked_reason` check (`account_inactive`,
   `membership_lost`). `replay` was **not** renamed: 0025 already named it,
   and the house rule is that the existing name wins.
2. **`SessionRepository.find_by_refresh_token` / `rotate`** — one read that
   answers *which session* **and** *which generation* of its token, and a
   conditional UPDATE that puts the presented hash in the WHERE clause, so
   two concurrent refreshes carrying one token cannot both win. `SessionRow`
   now carries `mfa`, because refresh re-mints the access token and dropping
   the claim would quietly demote every MFA session fifteen minutes in.
3. **`SessionService.refresh` / `revoke`** — the check order is the contract:
   resolve → grace-or-replay → account still active → membership still there
   → rotate → mint. **Roles are re-read from the membership on every
   rotation**, never carried over from the expiring token: a session must not
   outlive the rights it was opened with. The idle window slides forward on
   each rotation (`AUTH_REFRESH_TTL_SECONDS`, 30 days) but never past
   `AUTH_SESSION_ABSOLUTE_TTL_SECONDS` (90 days).
4. **`previous_refresh_token_hash` is always the token the last rotation
   replaced** — including on the grace path, where the caller presented the
   already-retired one. The outgoing token is live and somebody is holding
   it; orphaning it would sign that somebody out for losing a race they
   never knew they were in. `rotated_at` moves only when the presented
   token *was* the current one, so the window cannot be extended by
   re-presenting a token.
5. **The grace window** (`AUTH_REFRESH_GRACE_SECONDS`, 30 s, already
   contracted in `error-codes.md`). Inside it, a re-presented token is a
   dropped response and is answered with a fresh one; outside it, the same
   presentation is a replay — session revoked, identity denylisted,
   `auth.refresh_replay_detected` at `sec`. A grace retry deliberately does
   **not** re-stamp `rotated_at`, so a stolen token cannot renew its own
   grace.
6. **`routers/session_native.py`** — `POST /auth/refresh` and
   `POST /auth/logout`, serving both transports from one route: body for
   native (`X-Client-Type`), cookie for browsers. Denylist and audit live
   here; the metrics are the existing series.
7. **`auth_metrics.py`** — `mdx_auth_login_total`, `mdx_auth_refresh_replay_total`
   and `mdx_auth_logout_total` moved out of `routers/login.py` so both
   routers feed one series. `AuthRefreshReplay` in
   `infra/prometheus/rules/auth-audit.yml` alerts on
   `increase(mdx_auth_refresh_replay_total[5m]) > 0`; an alert that stops
   seeing replays because the detection moved file is worse than no alert.
8. **Mounting** — in native mode `session_native` serves the two paths and
   `login.router` (a Keycloak proxy in every line) is **not mounted at all**;
   in keycloak mode nothing changes. This is the rename A2 deferred, done as
   a mount rather than a file move. `/auth/login` therefore 404s in native
   mode, which is the truth: IDX-A4 owns the native password grant.
9. **Docs/config** — `AUTH_SESSION_ABSOLUTE_TTL_SECONDS`,
   `AUTH_REFRESH_GRACE_SECONDS` in `config.py`, `.env.example` and
   `docker-compose.override.yml`; `error-codes.md` updated to say which
   router serves which code in which mode, and that only the **last**
   retired generation is recognised as a replay.

## Delivered — macOS

| Issue | Delivered |
| --- | --- |
| M1-01 | `SessionStore.swift`: `StoredSession` (refresh token, expiry, identity id, email, last tenant), an actor over a `SessionStorage` seam, and `Keychain` extended with a service parameter and a returned `OSStatus`. A refused write is a thrown error, not a silent success. |
| M1-02 | `APIClient`: `X-Client-Type: macos` + `X-Request-Id` on **every** request to every service; body-carried refresh and logout; `URLSessionConfiguration.ephemeral` with `httpCookieStorage = nil`, `httpShouldSetCookies = false`, `httpCookieAcceptPolicy = .never`; persist-before-publish on rotation; keepalive removed; `LegacyCookies.purge()` at launch; `403 reauth_required` → one step-up → one retry. |
| M1-03 | `AuthResult` / `AuthResultDTO` / `IdentitySummary` / `MembershipSummary` / `EmailChallenge` / `ReauthOptions` in `Models.swift`; `Problem` grown a `requestId`, `retryAfter` and `attemptsLeft`; `AuthCopy.swift` — one map from machine code to sentence, and a request id on anything it does not recognise. |
| M1-04 | `PendingCaptures.swift` + `CaptureViewModel.process`: the recording is deleted **only** after `submitJob` succeeds; every other exit moves it to `~/Library/Application Support/Notes AI Capture/pending/` with a sidecar JSON. A failed move leaves the file where it is. Settings › Account shows the count and reveals them in Finder. |
| M1-05 | `SignInView` rebuilt as a step machine: email → six-digit code (`DSCodeField`: one hidden field under six boxes, so a paste is one ⌘V and the sixth digit auto-submits, resend countdown from the server's `resend_after`) → password (with "Forgot?" → `<web app>/reset`) → MFA (authenticator or recovery code) → welcome (`PATCH /auth/me`, skippable). The host name under the card expands into the four server URLs. |
| M1-06 | `ReauthSheet` + `AppState.presentReauth()` (the API actor asks, the sheet answers, the request retries once); `ReconnectingBanner`; `SessionLostReason` so the sign-in screen says *why*; `macos/README.md` sign-in table; 38 XCTest cases and a `macos-app` job in CI. |

### Two behaviours worth naming

* **A network error never costs a session.** Boot resolves to
  `signedOut` / `signedIn` / `offline`; only the first clears the Keychain
  item, and only when the server said so (`session_expired`,
  `auth_refresh_replay`, an expired stored token) — never on a timeout.
* **A replay is a different sentence.** `auth_refresh_replay` reaches the
  sign-in screen as "You were signed out for security. Sign in again."
  rather than as a blank form, and it is reported from the place that knows
  (the refresh), not inferred from the 401 that follows.

## Verification run here

**Against the dev stack** (`MDX_IDP_MODE=native docker compose up -d --build auth-service`,
restored to `keycloak` afterwards):

* a brand-new address → `/auth/email/start` → `/auth/email/verify` with
  `X-Client-Type: macos` → `status: authenticated`, `roles: [tenant_admin]`,
  **refresh token in the body**, `refresh_expires_in: 2592000`, and **no
  `Set-Cookie`**;
* `/auth/refresh` with that token → a new token, same `sid`, roles re-read;
* the retired token, re-presented **inside** 30 s → 200 with a fresh token,
  session untouched, `rotated_at` unmoved;
* the retired token, re-presented **after** 30 s → `401 auth_refresh_replay`,
  `auth_sessions.revoked_reason = 'replay'`, and the newest token dead too;
* two refreshes of the same token, back to back: both answered, and **both
  resulting tokens still work** — the winner is not orphaned by the loser's
  grace rotation;
* the audit trail reads `auth.signup` → `auth.login{method: email_code}` →
  `auth.refresh{client_type: macos}` → `auth.refresh_replay_detected` (`sec`);
* the browser transport in the same mode: cookie in, cookie rotated, no token
  in the body, `logout` → 204 → next refresh 401 (`revoked_reason = 'logout'`).
  That also lifts IDX-W1's first "Not met" — a native-mode SPA sign-in now
  survives a reload;
* migration 0030 applied, rolled back and re-applied.

**One bug this found that no stub could:** `revoked_reason` is a closed set
(0025), and the first replay 500'd on the check constraint. The reason is now
0025's own `replay`, and the two genuinely new reasons were added to the
constraint in 0030.

**Suites:** auth-service unit 330 passed (24 new, `test_session_native.py`);
macOS `swift test` 38 passed; `ruff check` and `ruff format --check` clean;
`mypy --strict` clean on the three new Python modules; `make check-rls`,
`check-identity-grants`, `check-metric-names`, `check-alert-rules`,
`check-no-os-environ`, `check-no-direct-asyncpg`, `lint-imports` all green.

**`make openapi-check` fails, and failed before this sprint too** — the
stale snapshot is `docs/api/note-service-openapi.json` (the Ask and spaces
routes of an earlier sprint). Verified by running it on a stashed tree.
The auth-service snapshot is unchanged, because it is dumped in keycloak
mode where the mounting is exactly as it was.

## Acceptance criteria

| Criterion | State |
| --- | --- |
| The refresh token exists only in the Keychain and survives a restart | Met. `SessionLifecycleTests.testSignInThenRefreshThenSignOut`, and the dev-stack run. |
| Zero background refreshes while idle; a 45-minute recording + upload succeeds with one refresh | Met by construction (the keepalive is gone; `needsFreshToken` is the only trigger) and asserted in `testALongRecordingCostsExactlyOneRefresh`. Not measured over a real 45 minutes. |
| A replayed refresh token signs the user out with the security message and clears the item | Met, in stubs and against the server. |
| No code path deletes a recording that was not uploaded successfully | Met. The only `removeItem` on a recording is guarded by `uploaded`. |
| Every new-flow error code has a user-facing message; unknown codes show a generic message with the request id | Met. `AuthCopyTests` covers the 21 codes these flows can raise. |

## Not met / not built

1. **`switch_tenant` and `POST /auth/token`.** Still A2's, still absent.
   `memberships` are decoded and held on `AppState` so IDX-M2's switcher has
   its data the moment the endpoint lands, and nothing here forecloses it.
2. **Native password sign-in.** The password screen is built and works
   against a keycloak-mode deployment, but that deployment answers no
   refresh token, so the app refuses the session (`APIError.noNativeSession`, with a
   sentence that names the server as the thing to fix) rather than
   pretending. In native mode `/auth/login` 404s and the screen
   takes the person back to the emailed code. IDX-A4 closes this; until
   then the Mac app's real way in is the code.
3. **A `CaptureViewModel` test.** The capture-safety rule is tested at
   `PendingCaptures` (five cases, including "a failed move leaves the file
   where it is"); the view model itself needs an `AppState`, whose `init`
   builds an `EventKit` service and starts a session restore. Standing up a
   seam for that is IDX-M2's work, alongside the pending-upload screen it
   will need anyway.
4. **Per-identity local state.** Signing in as a different identity replaces
   the Keychain item and clears the in-memory caches, but `recentCaptures`,
   `spaces` and the rest are still shared across identities in UserDefaults,
   exactly as the pack allows. Re-keying is M2's. The sidecar beside a kept
   recording *does* record the identity, so the pending list can be filtered
   from the start.
5. **`GET /auth/me` is not yet worth calling.** `hydrateIdentity()` is wired
   and is a no-op against today's `{claims, db_user}`; the account screen
   falls back to the address in the Keychain item. It starts working the day
   IDX-B2 extends the route.

## Debt

* **The estate's smoke scripts cannot run in native mode.**
  `scripts/smoke/notes_e2e.py` and `scripts/seed/seed.py` sign in with a
  password and send neither `X-Client-Type` nor `Origin`, so the origin
  check refuses them before `/auth/login`'s 404 would. This is a cut-over
  precondition, already recorded in A2's debt and unchanged by M1.
* **Replay detection is one generation deep.** The row has one slot for the
  retired hash, so a token two rotations old is answered `session_expired`
  and the session is left alone. Now stated in `error-codes.md`; a chain
  would need a table of its own and has not earned one.
* **`auth.session.revoked` is not written on a replay when the denylist is
  off.** The event is emitted next to the denylist push, so a deployment
  with `MDX_SESSION_REVOCATION_ENABLED=false` (the dev default) records the
  `sec` replay event but not the revocation. Worth moving when the denylist
  becomes mandatory.
* **`docs/api/auth-service-openapi.json` is still stale** (W1 recorded it
  three sprints ago) and now misses `/auth/refresh`'s native shape too.
* **The iOS app still holds its session in a cookie** and sends no
  `X-Client-Type`. `ios/` is a copy of this code, not a shared library, so
  IDX-I1 will repeat this sprint file for file — or the two should be given
  a shared package first. Worth deciding before I1 starts.
