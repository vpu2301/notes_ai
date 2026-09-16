# IDX-I2 — iOS: workspace context, pending uploads, offline, account

**Status:** four of the five issues delivered (2026-09-06). **I2-04
(invitation links) was not built** — invitations have no server, and the
user chose the pack's own first cut rather than carrying another sprint's
worth of backend. See §"The gate".
**Branch:** S01 (uncommitted working tree).
**Depends on:** I1 (landed) and B1 (never run).

## The gate, stated first

The pack's dependency line reads *"Depends on: I1, B1"*. I1 landed
yesterday. **B1 has never been run**, and this is the third sprint in the
programme to record it: IDX-W1 ("Two of the sprint's routes have no server
to talk to and were not built") and IDX-W2 ("members/invitations have no
server to talk to") said the same thing about the web app.

Checked against the repo rather than assumed:

| I2-04 needs | Reality |
| --- | --- |
| an invitations table | No `invitation` in any file under `infra/postgres/migrations/` (0001–0030). |
| create / preview / accept endpoints | No `invitations.py` in `services/auth-service/src/auth_service/routers/`; `grep -rn "invit" --include="*.py" services/` finds only `/admin/users/invite` (a Keycloak-era admin call that creates a **user row**, not a link) and unrelated calendar comments. |
| a web page to fall back to | No `/invite/:token` route in `web/src/App.tsx`. |
| an AASA file | `web/public/.well-known/` does not exist. |

So there was nothing to build a preview sheet against, and nothing for a
universal link to fall back to in Safari. Put to the user before any code
was written; the answer was to cut I2-04 — which is what the pack itself
nominates ("Cut first if over capacity: universal links") — and deliver
the rest in full.

**What was left in its place:** `AppState.AppLink` parses
`notesai://invite/<token>` and `notesai://notes/<id>`, `RootView` routes
`onOpenURL` through it, and an invitation link is answered with a sentence
that is true and actionable ("ask whoever sent it to add you to their
workspace from Notes AI instead" — `POST /tenants/{id}/members` does exist,
and the Mac app already drives it). The token is deliberately **not** kept:
nothing can redeem it, and an unredeemable credential in memory is only a
liability. When B1 lands, what is missing is the preview sheet and the
Associated Domains entitlement.

## What the rest of the pack found

| Item | Finding |
| --- | --- |
| `POST /auth/token` | **Exists** — `routers/session_native.py`, `SessionService.switch_tenant`, re-reading the membership before it mints. IDX-W2 recorded it as missing, and it was: IDX-M1 wrote it a day later, along with the rest of A2's session half. The switcher is therefore buildable on iOS before it is on the web. |
| `GET /auth/me` | Still the pre-IDX `{claims, db_user}` shape (IDX-B2 debt, recorded by M1 and I1). The pack asks for the membership refresh to go through it; it carries no memberships at all. **`GET /tenants`** — "Tenants the caller belongs to", `my_role` included, re-read from the table on every call — is the same fact and is what this sprint uses. |
| Sessions | `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others` all exist (IDX-A5). `revoke-others` is behind `Depends(recent_auth)` → `403 reauth_required`, which is the **first real caller** of the step-up plumbing IDX-I1 built and left with no endpoint to answer. |
| Local state | UserDefaults only, as the pack says: `recentCaptures`, `backendSettings`, `accountEmail`, `themePref`, plus the pre-0021 `spaces`/`spaceOfNote` that already migrate to the server. No App Group, no extensions. Only `recentCaptures` is anybody's data; the rest is device preference and stays unscoped. |
| `AppState.init` | Loaded the recents **before** knowing who was signed in. That is the bug I2-01 exists to fix, and it was live: sign in as a colleague on a shared phone and the previous person's meeting titles were on the home screen. |
| Spaces | Server-side since 0021 and scoped by the token's `tid`, so they need no local keying — they empty and refill on a switch because the server answers differently, which is the correct mechanism. |

## Delivered

| Issue | Delivered |
| --- | --- |
| I2-01 | `LocalStore.swift`: `StateScope` (identity + tenant), `ScopedDefaults` (read/write/enumerate/remove, with the scoped key list named once so the migration, the enumeration and the removal button cannot drift), `RecentsStore`, and a one-time migration of the unscoped `recentCaptures` into the first identity that signs in. `AppState` drives the scope from `adopt`/`complete`/`switchWorkspace`/`clearSignedInState` and writes nothing when there is none. `pending/` files and sidecars are written `.completeUntilFirstUserAuthentication`. |
| I2-02 | `Workspace`, `SwitchedToken`, `DeviceSession` in `Models.swift`; `APIClient.workspaces()`, `switchWorkspace(to:)`, `borrowToken(for:)`, and a `bearer:` parameter on `send` for a token that is not this session's. `submitJob(…, tenantId:)` borrows a token when the recording's workspace is not the open one. `SessionStore.rotateTenant` remembers the choice for the next launch. `WorkspaceChip` on Home, `WorkspacePicker` sheet, the workspace list in Settings › Account, and a membership refresh on foreground activation (`GET /tenants`, at most once every five minutes, or at once after a 403). |
| I2-03 | `PendingUploadsSection` at the top of Home: **Retry** (foreground pipeline, with the recording's own workspace), **Export** (share sheet), **Delete** (confirmation), **Send to <workspace>** (re-target). `PendingCaptures` grew `retarget`, `delete`, `sidecar(of:)`, `all(identityId:)`, `old(before:excluding:)` and `needsWorkspace(_:memberships:)`. `CaptureViewModel.process` was split so a retried recording joins the pipeline at `follow(jobId:…)`, and a recording is now bound to the workspace it was **started** in, not the one that is open when it stops. `WorkspaceLostBanner` for a membership removed under the app's feet. |
| I2-05 | `AccountView`: display name (`PATCH /auth/me`), workspaces with switch, the Face ID gate, sessions (list, end one, "sign out everywhere else" → step-up sheet → retry), a link out to the web app for passwords and second factors, what this phone is holding, "remove local data for other accounts", "old recordings", and a sign-out that warns when recordings are waiting. Settings' account group became a row that pushes it. |
| I2-04 | **Not built** — see §"The gate". The URL seam and its tests are in place. |

### Three decisions worth naming

**An upload borrows a token; it does not move the session.** A recording
made for the agency and retried a day later, after the person has switched
to a client workspace, still belongs to the agency. `POST /auth/token` with
`activate: false` mints a token for that workspace for that one request.
The session stays where the person put it, and a 401 on a borrowed token is
reported as what it is — a membership that is gone — rather than triggering
a refresh, a retry and eventually a sign-out.

**A recording is bound when it starts, not when it stops.** Switching
workspaces during a meeting must not re-file the meeting. `CaptureViewModel`
captures `app.tenantId` at `recorder.start()`, and that is what reaches
both `submitJob` and the sidecar.

**The membership list is never emptied by a failed request.** A 403 on the
notes list asks `GET /tenants` immediately; a timeout changes nothing. The
list the app holds is the last one the server confirmed, which on a phone —
where the network is the normal failure — is the difference between a
banner and a sign-out.

## Verification run here

* `ios/scripts/check.sh` — 31 files compile for `arm64-apple-ios17.0-simulator`, no warnings.
* `xcodebuild … build-for-testing` — **TEST BUILD SUCCEEDED**, app and test bundle, no warnings.
* `ios/scripts/build-sim.sh Release` + `ios/scripts/check-ats.sh` — still `NSAllowsArbitraryLoads = false`.

**The tests were not executed here**, for the same reason as in IDX-I1:
they are an app-hosted XCTest bundle, running them boots a simulator, and
`ios/CLAUDE.md` forbids this assistant from booting one. The `ios-app` CI
job runs them. **No dev-stack run**: `POST /auth/token`, `GET /tenants` and
the three session endpoints were read in the source and stubbed in the
tests, not exercised against a running auth-service.

## H. Tests

| Test | Where |
| --- | --- |
| switch workspace: no cross-tenant state | `ScopedStateTests.testTwoWorkspacesDoNotSeeEachOthersMeetings`, `…TwoIdentitiesDoNotSeeEachOthersMeetings`, `…AScopeIsNotAPrefixOfAnother` |
| legacy state migration, once | `testTheOldUnscopedMeetingsMoveToTheFirstIdentityThatSignsIn`, `testTheMigrationRunsOnce`, `testAFreshInstallHasNothingToMigrate` |
| removing another account's data | `testEveryScopeOnThePhoneCanBeListedAndRemoved` |
| the switch itself | `WorkspaceTransportTests.testSwitchingPublishesTheNewTokenAndRemembersTheWorkspace` |
| an upload keeps its own workspace | `testAnUploadForAnotherWorkspaceBorrowsATokenWithoutMovingTheSession`, `testAnUploadForTheActiveWorkspaceBorrowsNothing` |
| membership removed → no session loss | `testABorrowedTokenThatIsRefusedDoesNotCostTheSession` |
| pending re-target / delete / ownership | `PendingCaptureTests.testARecordingCanBeSentToAnotherWorkspace`, `…DeletingTakesTheSidecarWithIt`, `…OnlyThisIdentitysRecordingsAreListed` |
| never upload to a workspace you left | `testARecordingIsUploadableOnlyToAWorkspaceItsOwnerIsStillIn` |
| old recordings are listed, never swept | `testOldRecordingsAreOnlySomebodyElsesAndOnlyAfterAMonth` |
| data-protection class | `testKeptFilesAreReadableAfterTheFirstUnlockAndNotBefore` (the class itself is asserted everywhere; the file attribute only off-simulator, where the simulator's filesystem reports none) |
| sessions revoke-others → step-up → retry | `testSigningOutEverywhereElseStepsUpAndRetriesOnce` |
| the session list names this phone | `testTheSessionListNamesThisPhone` |
| link routing (I2-04 seam) | `AppLinkTests` — including that the two OAuth callbacks are **not** app links, since anything that could route them here could replay them |

## I. Acceptance criteria

| Criterion | State |
| --- | --- |
| Local state separated per identity and tenant; switching never shows another tenant's recents or spaces | Met. Recents are keyed and tested; spaces come from the server under the new token and are cleared on the switch. |
| No path deletes a not-yet-uploaded recording without explicit user action | Met. `PendingCaptures.delete` has exactly one caller, behind a confirmation dialog; the retry deletes only after `submitJob` returns. |
| Invitation universal links and scheme links both reach the preview sheet | **Not met — not built.** See §"The gate". |
| The app never refreshes from a locked/background state, and never needs the gate key for an in-flight upload | Met by IDX-I1's construction and unchanged here: the gate key is needed only to read the refresh token, the access token in memory carries the upload, and nothing runs while the app is not on screen. |

## Not delivered (and where it goes)

* **I2-04 in full** — blocked on IDX-B1. The seam and its tests are here.
* **Background uploads** — IOS-S1 in the Foundation pack. Until then a
  retry needs the app on screen, and the pending section says so.
* **Workspace settings and member management on the phone** — not in this
  pack for iOS; the account screen links out to the web app.
* **`GET /auth/me` carrying identity and memberships** — still IDX-B2's.
  Two clients now work around it the same way.
