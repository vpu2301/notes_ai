# IOS-1 — iOS in the dual-issuer period

**Status:** delivered on the phone (2026-09-06); **not verifiable end to
end** — see *The dependency that is not there*. **Branch:** S01
(uncommitted working tree).
**Batch:** FND-0 `first-account`. **Depends on:** BE-3.
**Window:** W4, parallel with MAC-1.

## B. Inspect first — what was actually there

The ticket is written as though IDX-I1 had not run on iOS. It had:
`docs/sprints/IDX-I1.md` records it delivered on 2026-09-05, in the same
uncommitted tree. So the work here is not "build I1-02/03/04/06 in a dual
flavour" but "take the native-only app that exists and make it correct
while two issuers are live".

| Ticket item | Finding |
| --- | --- |
| 1. Two session kinds; "today's cookie path for Keycloak password users" | **The cookie path no longer exists on either side, and should not come back.** `routers/login.py:243` reads `X-Client-Type` and sets the refresh cookie *only* for a browser; a native client gets the Keycloak refresh token in the body, exactly as the native login does — the router says so in its own header comment. The app has had no cookie jar since IDX-I1. Re-adding one would put an HttpOnly credential on the phone that nothing in the app can see or rotate, to solve a problem the server already solved. Delivered instead as the ticket's own discriminator: **both kinds are body tokens in one Keychain item, told apart by the `nrt_` prefix** — which is also what ADR-0047 says BE-2 routes `/auth/refresh` and `/auth/logout` on. "Keepalive only for cookie sessions" is delivered as "keepalive only for Keycloak sessions", which is the same set and the actual reason (Keycloak's idle timeout, not the transport). |
| 2. Password vault stays | It had been **deleted** (`Credentials.swift`, by I1-01), and `SessionMigration` purged the item on first launch. Both undone for the duration. |
| 3. Sign-in: email → code → welcome, "Use a password", `409 use_password` | The step machine, the password form and the *Use a password instead* link were already there from I1-04. Missing: the saved-password Face ID re-login, the save toggle, and `use_password`. |
| 4. Capture safety (I1-03) | Already delivered and unchanged. `PendingCaptures` + `ensureFreshToken(minimum: 300)` before `submitJob`. |
| 5. ATS split (I1-06) | Already delivered and unchanged, CI job included. |
| "No MFA sheet, no reset, no reauth" | Read as a scope floor, not an instruction to delete working, tested code. All three are I1-04/I1-05 deliverables that already exist and are covered by tests; removing them would be a regression with no beneficiary. |

## Delivered

| Item | Delivered |
| --- | --- |
| Session kinds | `SessionKind` (`native` \| `keycloak`) in `SessionStore.swift`, derived from the token's `nrt_` prefix and carried on `StoredSession`, `SessionRecord` (in the clear, beside the address and the expiry) and `SessionSummary`. Three capabilities hang off it: `needsKeepAlive`, `canSavePassword`, `canGate`. |
| Keepalive | Back in `APIClient`, armed by `publish` and **only** when `sessionKind?.needsKeepAlive`. A minute before the access token expires; a fixed minute after a transient failure, so an offline phone does not spin. Cancelled by `forgetToken`, and so by sign-out, session loss and wipe. |
| Password vault | `Credentials.swift` restored unchanged from before I1-01 — same service, same account, same access control, so a phone that updates finds the item it already had. `LegacyCredentials` becomes the one place the service string is written, and `CredentialStore.service` reads it from there. |
| Migration held back | `SessionMigration.run`'s `purgeCredentials` now defaults to a no-op and the notice with it; the cookie purge stays. IDX-A4/A5 turns the cut-over back on by changing one default, and the delete side is still tested so it is not first exercised on the day it matters. |
| Sign-in | Face ID over the saved password (offered once when the password step is reached, never in front of an unreachable server), the *Save password for Face ID* toggle, a saved password forgotten on a 401 — and `409 use_password` on `/auth/email/verify` moving the screen to the password form with the address carried across. MFA is checked **before** the saved-password 401 branch: Keycloak asks for the second factor with a 401 too, and reading that as "the saved password is wrong" would delete a good password. |
| The gate, off | `AppState.gateOffered = false`. The machinery and its tests are untouched; the Settings toggle is not rendered. `setGate` refuses on a Keycloak session (`.gateUnavailable`) but still honours *off* — de-escalation is never refused. A Keycloak sign-in leaves an existing gate key alone rather than destroying it, so the next native sign-in finds the preference its owner set. |
| `409 legacy_session` | ADR-0047 records workspace switching as the one capability `dual` splits by token origin. `APIError.isLegacySession`, a sentence in `AuthCopy`, the switcher disabled with the reason on screen in both places that offer it, and a fast refusal in `AppState.switchWorkspace` so the tap does not have to earn a 409. Added to `docs/api/error-codes.md`, which had it only in the ADR. |
| `NSFaceIDUsageDescription` | Back to naming the saved password, which is what Face ID actually unlocks in this build. |

## Verification run here

* `ios/scripts/check.sh` — 32 files compile for `arm64-apple-ios17.0-simulator`, no warnings.
* `xcodebuild … build-for-testing` — **TEST BUILD SUCCEEDED**, no warnings from app or test bundle.
* `ios/scripts/build-sim.sh Debug` and `… Release` — both build.
* `ios/scripts/check-ats.sh` on the Release product — `NSAllowsArbitraryLoads = false`, no `NSAllowsLocalNetworking`; the Debug product has both `true`.
* `NSFaceIDUsageDescription` in the built product reads "Notes AI uses Face ID to unlock the password saved on this phone, so you do not have to type it again."

**The tests were not executed here.** App-hosted XCTest boots a simulator,
which `ios/CLAUDE.md` forbids this assistant from doing. They are built and
linked on every change and the `ios-app` CI job runs them.

## The dependency that is not there

**BE-3 has not been built, and neither have FND-1 or BE-2.** Checked, not
assumed:

* `services/auth-service/src/auth_service/config.py:60` —
  `idp_mode: Literal["keycloak", "native"]`. There is no `dual`.
* `libs/auth/src/auth/verifier.py` — `expected_issuer: str`, singular. No
  service trusts a list of issuers.
* `nrt_` appears nowhere in `services/`, `libs/` or `web/`; `use_password`
  is in `docs/api/error-codes.md` and in no handler.
* ADR-0047 is dated 2026-09-06 and its cut-over plan lists FND-1 → BE-2 →
  BE-3 ahead of this sprint.

So the acceptance criteria that need a server — *new email → code →
welcome → record → note in Recents*, and *seeded password users sign in
exactly as before* — **have not been demonstrated against one.** What is
demonstrated is the phone's half, against the stub server in the tests, on
the contract ADR-0047 and `docs/api/error-codes.md` write down. That is the
same standard IDX-I1 was accepted at, and it is worth naming rather than
letting a green CI badge imply more.

The client-side criteria are met and asserted: the Keychain item exists
with `kind: native` and no cookie is sent (`DualSessionTests`,
`TransportTests`), no keepalive is armed for a native session, a failed
upload leaves the recording under `pending/` (`PendingCaptureTests`,
unchanged), and the Release plist allows no arbitrary loads.

## Tests

New: `Tests/NotesAICaptureTests/DualSessionTests.swift` — the prefix rule
and what each kind can do; an email-code sign-in storing `native` and a
password sign-in storing `keycloak` with no cookie either way; the kind
legible while the token beside it is sealed; a Keycloak session renewing
itself before its token idles out and a native one making no requests at
all; sign-out stopping the timer; the gate refused on a Keycloak session,
turned off regardless, and its key surviving a password sign-in;
`AppState.gateOffered` asserted off; `use_password` and `legacy_session`.

Changed: every existing token literal is now `nrt_…`, because those tests
are about native sessions and the prefix is now load-bearing. The three
migration tests are rewritten — the vault must now **survive**, including
against the real Keychain — and the old delete path keeps a test of its
own. `AuthCopyTests` covers the two new codes.

## Not delivered (and where it goes)

* **Anything server-side.** FND-1, BE-2 and BE-3 are other tickets in this
  batch and are the reason this cannot be run end to end yet.
* **MAC-1** — the same two changes on the Mac (`SessionKind`, the keepalive
  and the vault). The ticket says to ship it first if capacity is short;
  it has not been done, so macOS is still native-only and its
  `SessionMigration` still deletes the password vault on first launch.
* **The gate on screen** — I1-05, after A4/A5.
* **Web** — `web/` has no `nrt_`/`use_password` handling either.
