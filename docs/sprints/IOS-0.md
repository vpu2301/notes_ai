# IOS-0 — nothing to build for signup; one link, and a smoke that cannot run in CI yet

**Status:** item 1 delivered (2026-09-06); item 2 delivered as a runnable
artefact, **not as a green CI job** — see below. **Branch:** S01
(uncommitted working tree). **Batch:** FND-0 `first-account`.
**Depends on:** BE-0. **Window:** W1.

## B. Inspect first

**BE-0 does not exist.** Checked, not assumed:

* no `signup` router in `services/auth-service/src/auth_service/routers/`;
* `email_not_verified` and `/auth/signup/*` appear in no handler, no test
  and no OpenAPI snapshot;
* `web/src/pages/` has `LoginPage`, `auth/PasswordLoginPage`,
  `auth/WelcomePage`, `auth/ResetPasswordPage` — and no signup page, so
  `<webAppURL>/signup` is a link to a route that 404s today;
* `BE-0` is not mentioned anywhere in the repository.

Two other things worth recording, because they change what "no change
beyond the two items" means:

| Item | Finding |
| --- | --- |
| "the Face ID password vault (`CredentialStore`) works for it as for anyone else" | **True now, and it was not two days ago.** IDX-I1 *deleted* `Credentials.swift` and had `SessionMigration` purge the vault on first launch. IOS-1 (W4, executed before this) restored both for the dual period. Had IOS-0 run in its own window against the IDX-I1 tree, this premise would have been false and the ticket would have needed a third item. |
| "`/auth/login` with email + password" | Intact and exercised. `routers/login.py` honours `X-Client-Type: ios` and returns the refresh token in the body, so a BE-0 account is an ordinary body-token session on the phone. |

## Delivered — item 1

| Piece | Where |
| --- | --- |
| "Don't have an account? **Create one**" → `<webAppURL>/signup` in Safari | `Views/SignInView.swift` (email step), `AppState.openSignup()`, built off the configured web app rather than the auth host — on a phone those are different machines. |
| `403 email_not_verified` | `APIError.isEmailNotVerified`, a sentence in `AuthCopy`, and a notice that turns from red to blue with an envelope: an unconfirmed address is not a wrong password, and the way forward is a click in an inbox rather than a retry. |
| **Resend the confirmation email** | `APIClient.resendVerification(email:)` → `POST /auth/signup/resend` (unauthorised — the caller cannot sign in, which is the problem), `AppState.resendVerification(to:)`. It reports on success as well as failure: this is the one button in the flow where nothing visible happens otherwise, and silence reads as broken. |
| The contract, written down | `docs/api/error-codes.md` gains `email_not_verified` (403, `POST /auth/login`) and a paragraph on its partner endpoint. It had neither; the client now depends on both. |
| Tests | `Tests/NotesAICaptureTests/SignupTests.swift` — the code is recognised and worded; **`account_disabled` is not mistaken for it** (both are 403s from the same endpoint and they want opposite things from the person: an inbox, or an administrator — offering "resend" for a disabled account sends them round a loop that cannot end); a 401 is not either; resend sends the address unauthenticated with `X-Client-Type: ios`; a rate limit surfaces instead of claiming success; and the signup URL is built off `webAppURL` for both `localhost` and a LAN host. |

One ordering rule made explicit while adding the 403: nothing that is *not*
a rejected password may reach the branch that deletes a saved one. MFA
(a 401) and `email_not_verified` (a 403) are both caught above it.

## Delivered — item 2, and the part of it that cannot be

The ticket asks for the smoke in the **`ios` CI job, on the simulator**.
That is not possible on this repository today, and the reason is not
effort:

1. **No stack.** No job in `.github/workflows/ci.yml` stands up any
   service — there is not one `services:` block or `docker compose` in the
   file. The smoke needs auth-service, note-service, asr-service, an
   asr-worker, Postgres, Redis and a mail sink.
2. **No Docker on the runner.** The `ios-app` job runs on `macos-15`,
   which is where SwiftUI must be compiled and where Docker is not
   available.
3. **No microphone.** A simulator on a CI runner has no audio input
   device, so `Recorder` is the one step of this pipeline a machine
   without a microphone cannot exercise at all.
4. **No BE-0.** Account creation and confirmation are its endpoints.

**This project has already made this decision once, for the same reason.**
`ci.yml:165-169` says the web's Playwright first-use suite is deliberately
not run in CI because it waits on a real transcription and the asr-worker
image bakes whisper-large-v3 (2.7 GiB); `make web-e2e` runs it against the
dev stack. IOS-0 is delivered the same way, so the estate has one answer
rather than two:

| Half | Where | Runs |
| --- | --- | --- |
| API — create + verify the account, sign in **as the phone signs in**, upload 1 s, poll the job, make the note, read it back | `scripts/smoke/ios_signup_e2e.py`, `make smoke-ios` | Against `make dev-up`. Exit 2 (not 1) when the stack is unreachable: a missing fixture is not a failed assertion. |
| App — the same path through the app's own `APIClient`, ending with the capture in `RecentsStore` | `Tests/NotesAICaptureTests/LiveStackTests.swift` | `NOTES_STACK_HOST=localhost ios/scripts/test.sh`. Skips otherwise. |
| CI | a guarded step in the `ios-app` job | `if: vars.NOTES_STACK_HOST != ''`. A visible skip today; both halves run the moment the variable points at a stack. |

Three decisions inside that worth naming:

**Every request carries `X-Client-Type: ios`.** Without it the server takes
the caller for a browser and answers on the web's branch — cookie, no body
token — and the smoke would prove nothing about the phone. The script
asserts both halves of that invariant: a `refresh_token` in the body, and
no `Set-Cookie`.

**The account step degrades instead of failing.** When `/auth/signup`
answers 404 the script says so, falls back to the seeded user, and runs
every step after it. "The account is new" is the only claim it cannot make
until BE-0 lands; losing the other five with it would leave the whole path
untested for as long as BE-0 takes.

**One second of audio is generated, not recorded.** A 16 kHz mono WAV — the
format `Recorder` itself falls back to when FLAC is unavailable, so the
upload path under test is one the app really uses — carrying a 440 Hz tone
rather than silence, because an all-zero buffer is the kind of input a
decoder is entitled to reject.

## Verification run here

* `ios/scripts/check.sh` — 32 files compile, no warnings.
* `xcodebuild … build-for-testing` — **TEST BUILD SUCCEEDED**, no warnings
  from the app or the test bundle, `SignupTests` and `LiveStackTests`
  included.
* `ios/scripts/build-sim.sh Release` + `check-ats.sh` — still green.
* `scripts/smoke/ios_signup_e2e.py --help` runs; against an unreachable
  host it exits **2** with the right message.
* The generated WAV was written to disk and read back by `afinfo`:
  `1 ch, 16000 Hz, Int16, estimated duration: 1.000000 sec`.
* `.github/workflows/ci.yml` parses, and the new step carries its guard.

**Not run:** the smoke itself, either half. Both need the stack up, and
`make dev-up` is not something to start unasked; the app half also needs a
simulator, which `ios/CLAUDE.md` forbids this assistant from booting. So
the acceptance criteria stand as follows:

| Criterion | State |
| --- | --- |
| A BE-0 account signs in and records on iOS with no change beyond the two items | **Cannot be demonstrated.** BE-0 has no endpoints. The claim's other half — that such an account is an ordinary password account here — is true by construction and unit-tested. |
| CI smoke green after every BE-0 change | **Not met, and not meetable today** for the four reasons above. The artefacts exist, compile on every push, and turn on with one repository variable. |

## Not delivered (and where it goes)

* **BE-0** — the signup, confirm and resend endpoints, and the web
  `/signup` page the new link points at. Both are other people's tickets
  in this batch; until they land the link goes to a 404 and the resend
  button to one.
* **A CI-reachable stack.** If the smoke is wanted green, that is the
  decision to take — a long-lived staging stack the macOS runner can
  reach, or splitting the API half onto an `ubuntu-latest` job that can
  run `docker compose`. Worth deciding once for `web-e2e` and this
  together rather than twice.
* **The microphone.** `Recorder` stays covered by the app's own tests and
  by hand. No CI runner will exercise it.
