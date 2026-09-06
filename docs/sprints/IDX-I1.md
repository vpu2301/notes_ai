# IDX-I1 — iOS: Keychain sessions (optionally biometric-gated), sign-in flows

**Status:** delivered (2026-09-05). **Branch:** S01 (uncommitted working tree).
**Depends on:** A5 — and, in practice, on IDX-M1, which carried the server
half both sprints needed (`SessionService.refresh`/`revoke`,
`routers/session_native.py`, migration 0030). Nothing on the server was
written here; this sprint is the phone.

## B. Inspect first — what was actually there

| Item | Finding |
| --- | --- |
| `APIClient` | Was **not** byte-for-byte the macOS actor: it was the *pre-M1* one (513 lines against 818). Cookie storage `.shared`, `LoginResponse`, `scheduleKeepAlive`, `sessionLost()` with no reason, no `X-Client-Type`, no `X-Request-Id`, no `Problem` extras, no step-up. So this was a port of M1's client, not a copy of a shared file. |
| `Credentials.swift › CredentialStore` | As described: service `ai.notes.capture.credentials`, `.biometryCurrentSet`, `load(reason:)` on a detached task, `hasSaved` via `interactionNotAllowed`. The access-control pattern was reused for the gate key; the file is **deleted** — `Biometrics` (name/symbol/availability) and `LegacyCredentials` (delete-only) took its place in `SessionStore.swift`. |
| `Connectors/ConnectorStore.swift › enum Keychain` | As described, and `write` discarded its `OSStatus`. Extended exactly as M1 extended the Mac's: service parameter, returned status, `kSecAttrSynchronizable: false`. |
| `Views/SignInView.swift` | As described, plus `DSToggleStyle`, the "Save password for Face ID" toggle and the saved-password error path. Rebuilt as the step machine; `BackendSettings.forHost` / `pointsAtLocalhost` / `isPhysicalDevice` and the localhost-on-a-phone guidance are kept, because on a phone they are the difference between "cannot sign in" and "cannot sign in *because the address is the phone itself*". |
| `Views/Components.swift` | No `DSCodeField` (that is macOS-only, added by M1). One was written for touch: full-width boxes, `.numberPad`, `textContentType(.oneTimeCode)` so the keyboard's own "From Messages" suggestion fills it. |
| `Support/Info.plist` | As described. `NSFaceIDUsageDescription` named the saved password; changed. |
| `CaptureViewModel.process` | `defer { removeItem }` on every exit, as on the Mac before M1. |
| Tests / CI | **None**, and no iOS job in `.github/workflows/ci.yml`. The iOS app had never been compiled by CI at all. |

One correction to §D worth recording: the pack says the gate item is
created with `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` **and**
`.biometryCurrentSet`. That is right on a phone with biometry enrolled and
impossible on one without — `SecItemAdd` refuses the item. §J asks for a
passcode fallback in that case, so `KeychainSessionGate.create()` uses
`.userPresence` when `Biometrics.name` is nil and `.biometryCurrentSet`
otherwise. The gate is still device-bound and still passcode-required; only
the "re-enrolment invalidates it" property is unavailable where there is
nothing enrolled to change.

## Delivered

| Issue | Delivered |
| --- | --- |
| I1-01 | `SessionStore.swift`: `SessionRecord` (what the item holds), `StoredSession` (what the app uses), `SessionSummary` (what can be read without a face), an actor over two seams — `SessionStorage` and `SessionGateKeyring` — plus `Biometrics`, `LegacyCookies`, `LegacyCredentials` and `SessionMigration`. `Keychain` grew a service parameter and a returned `OSStatus`: a refused write is a thrown error, not a silent success. `Credentials.swift` deleted. `Info.plist` strings updated. |
| I1-02 | `APIClient`: `X-Client-Type: ios` + `X-Request-Id` on **every** request to every service; body-carried refresh and logout; `URLSessionConfiguration.ephemeral` with `httpCookieStorage = nil`, `httpShouldSetCookies = false`, `httpCookieAcceptPolicy = .never`; persist-before-publish on rotation; keepalive removed; `LegacyCookies.purge()` at launch; `403 reauth_required` → one step-up → one retry; `Restore` grew a `.locked` case. `Models.swift` gained the M1 auth types (`AuthResult`/`AuthResultDTO`, `IdentitySummary`, `MembershipSummary`, `EmailChallenge`, `ReauthOptions`, `MeResponse`, `ReauthPrompt`, `SessionLostReason`, a `Problem` with `requestId`/`retryAfter`/`attempts_left`) and `AuthCopy.swift` came across with the wording changed from "this Mac" to "this phone". |
| I1-03 | `PendingCaptures.swift` + `CaptureViewModel.process`: the recording is deleted **only** after `submitJob` succeeds; every other exit moves it to `<Application Support>/pending/` with a sidecar JSON. A failed move leaves the file where it is. `submitJob` also calls `ensureFreshToken(minimum: 300)` first, so a 45-minute meeting does not discover an expired token with the audio already on the wire. |
| I1-04 | `SignInView` rebuilt as a step machine: email → six-digit code (`DSCodeField`, resend countdown from the server's `resend_after`) → password (with *Forgot?* → `<web app>/reset` in Safari) → MFA (authenticator or recovery code) → welcome (`PATCH /auth/me`, skippable). The "Server…" affordance and the localhost guidance survive; a `URLError` still opens the server field, because that is the failure this app actually has in the field. |
| I1-05 | `ReauthSheet` + `AppState.presentReauth()` (the API actor asks, the sheet answers, the request retries once); `ReconnectingBanner` as a top safe-area inset; `LockedView`; `SessionLostReason` so the sign-in screen says *why*; Settings › Signed in as: the gate toggle, the pending-recordings count, and **"Forget" removed** — there is no password to forget. |
| I1-06 | `Support/Config/{Common,Debug,Release}.xcconfig` and an `#if DEV_HTTP` in `Info.plist`; a `NotesAICaptureTests` target in the hand-written project plus a shared scheme; `scripts/test.sh`, `scripts/check-ats.sh`; an `ios-app` job in CI; `ios/README.md` and `ios/CLAUDE.md`. |

### Three decisions worth naming

**The gate encrypts, it does not merely mark.** With the gate on, the item
still carries the identity, the address and the expiry in the clear —
because the boot path has to know whether there is a session and whose it
is *before* it can put a face prompt on screen — and the refresh token is
an AES-GCM sealed box whose key lives in a second item. Copying the session
item off the phone therefore yields a token nothing can open, and the AEAD
tag means a wrong key fails loudly rather than producing plausible bytes.

**Two items, because two accessibility classes.** The session is
`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: an upload that finishes
while the phone is in a pocket has to be able to refresh. The gate key is
`kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` + `.biometryCurrentSet`:
it must not be readable without a face. One item cannot be both.

**Re-enrolment is a sign-out, not an error.** `.biometryCurrentSet` drops
the key when a face is re-enrolled. `SessionStore.unlock` turns the
resulting `errSecItemNotFound` into `.gateLost`, **clears the session item**
and lets `AppState` say so — an item nothing can ever open again is not a
session, and leaving it there would make every later launch ask for a face
that no longer works.

## Verification run here

* `ios/scripts/check.sh` — 27 files compile for `arm64-apple-ios17.0-simulator`, no warnings.
* `xcodebuild … -destination 'generic/platform=iOS Simulator' build-for-testing` — **TEST BUILD SUCCEEDED**: the app and the test bundle compile and link, no warnings from either.
* `ios/scripts/build-sim.sh Debug` and `… Release` — both build.
* `ios/scripts/check-ats.sh` on the Release product:
  `NSAllowsArbitraryLoads = false`, no `NSAllowsLocalNetworking`.
  The Debug product has both `true`, which is what the dev stack needs.
* `NSFaceIDUsageDescription` in the built product reads "Notes AI uses Face ID
  to unlock your session on this phone."

**The tests were not executed here.** They are an app-hosted XCTest bundle,
so `xcodebuild test` boots a simulator, and `ios/CLAUDE.md` forbids this
assistant from booting one. They are built and linked on every change, and
the new `ios-app` CI job runs them (`scripts/test.sh "iPhone 16"`) along
with the Release ATS assertion. Run `ios/scripts/test.sh` locally to see
them pass.

**No dev-stack run.** Unlike IDX-M1, which was verified end to end against
`MDX_IDP_MODE=native`, this sprint was verified against the stub server in
the tests and by construction: the transport is the same one M1 proved
against the real auth-service, with `macos` → `ios` in one header.

## K. Tests

| Test | Where |
| --- | --- |
| login → Keychain item exists, no cookie, `X-Client-Type: ios` | `SessionTests.testCodeSignInPutsTheRefreshTokenInTheKeychain`, `TransportTests.testEveryRequestDeclaresItselfAsThisApp`, `testNoCookieIsEverSentToTheAuthHost` |
| gate on: the token is unreadable without the key; a wrong key fails AEAD | `testWithTheGateOnTheTokenIsNotInTheItem`, `testAGatedItemIsUnreadableInAFreshLaunch`, `testTheWrongKeyDoesNotOpenTheItem` |
| biometry change | `testChangingTheBiometryWipesTheSession` |
| the gate survives a sign-out and a second sign-in | `testSigningInAgainKeepsTheGateOn` |
| the gate stops the client before anything is sent | `testAGatedSessionStopsTheClientBeforeAnythingIsSent` |
| concurrent 401s | `testTwoConcurrentUnauthorisedRequestsShareOneRefresh` |
| replay | `testAReplayedRefreshTokenWipesTheSessionAndSaysWhy` |
| migration | `testMigrationRemovesThePasswordAndSaysSoOnce`, `testAFreshInstallIsNotToldAboutAPasswordItNeverHad`, `testNoItemOfThisAppsHoldsAPasswordAfterTheMigration` |
| MFA flow | `testMFAIsAnAnswerAndNotASession` |
| a failed upload keeps the recording | `PendingCaptureTests` (5 cases) |
| pre-upload token freshness | `testAnUploadRefreshesBeforeItStartsWhenTheTokenIsNearlySpent` |
| Release ATS | `scripts/check-ats.sh`, in CI |
| every error code has a sentence | `AuthCopyTests` (6 cases, 21 codes) |

## L. Acceptance criteria

| Criterion | State |
| --- | --- |
| After update, no Keychain item contains a password | Met. `SessionMigration` deletes the `ai.notes.capture.credentials` service on the first launch; `testNoItemOfThisAppsHoldsAPasswordAfterTheMigration` asserts it against the real Keychain, `testMigrationRemovesThePasswordAndSaysSoOnce` against the seam. |
| Gate off: cold start signs in silently via refresh | Met. `SessionLifecycleTests.testSignInThenRefreshThenSignOut`. |
| Gate on: the face is required before any request carrying a token is sent | Met. `testAGatedSessionStopsTheClientBeforeAnythingIsSent` asserts the stub server saw **nothing**. |
| A replayed refresh token results in a security sign-out and a cleared item | Met, in stubs. Against a real server this is M1's evidence, unchanged. |
| No code path deletes a recording that was not uploaded successfully | Met. The only `removeItem` on a recording is guarded by `uploaded`. |
| Release configuration does not allow arbitrary loads | Met, and asserted on the built product in CI. |

## Not delivered (and where it goes)

* **Pending-uploads UI** — Settings shows the count; retrying is IDX-I2's.
* **Workspace switcher, invitations, universal links, offline rules, MFA
  enrolment** — IDX-I2, as the pack says.
* **The step-up sheet has no caller yet.** `403 reauth_required` is
  plumbed end to end and tested, but no endpoint this app calls returns it
  today. Same position as macOS after M1.
* **Background `URLSession` uploads** — IOS-S1 in the Foundation pack, not
  this program. Until then an upload that the system suspends fails into
  `pending/`, which is exactly why I1-03 exists.
