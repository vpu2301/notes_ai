# API error codes

Machine-readable `code` carried as an RFC 9457 extension member on problem
responses (`problem_extras["code"]` on the raising side). Clients branch on
`code`; `detail` is for people and may change.

| Code | Status | Where | Meaning / client action |
| --- | --- | --- | --- |
| `auth_refresh_replay` | 401 | `POST /auth/refresh` | A rotated refresh token was presented after its `AUTH_REFRESH_GRACE_SECONDS` (30 s) grace. The session is revoked and the account's access tokens denylisted. Clear local state and sign in again; never retry. Only the token the *last* rotation retired is recognised: an older one is no longer attributable to the session and answers `session_expired` instead, leaving the session alone. |
| `session_expired` | 401 | `POST /auth/refresh` | Idle (`AUTH_REFRESH_TTL_SECONDS`, slid forward by each rotation) or absolute (`AUTH_SESSION_ABSOLUTE_TTL_SECONDS`) lifetime passed — or the session was revoked, or the token belongs to no session at all. One code for all of them: which it was is a fact about somebody else's account. Sign in again. |
| `no_refresh_token` | 401 | `POST /auth/refresh` | Neither the `mdx_rt` cookie nor a body `refresh_token` was sent. |
| `session_revoked` | 401 | `POST /auth/token`, `GET /auth/me` | The bearer's `sid` no longer matches a live session row (logout, revoke-all, replay). Sign in again. |
| `account_disabled` | 403 | session endpoints, `POST /auth/email/verify` | The identity is `disabled`. Show the account-state message; no retry. (A `pending_deletion` identity is NOT refused — signing in cancels the deletion.) |
| `not_a_member` | 403 | `POST /auth/token` | The identity has no membership in the requested workspace. |
| `membership_suspended` | 403 | `POST /auth/token` | Membership exists but is suspended. |
| `tenant_dissolved` | 403 | `POST /auth/token` | The workspace itself has been closed. Distinguished from `not_a_member` because the caller *was* one and their local copy of that workspace should say so. |
| `no_workspace` | 409 | session start / refresh, `POST /auth/email/verify` | No active membership anywhere. A signup always creates one, so this is only reachable if the last membership was later removed (IDX-B1). |
| `signup_rate_limited` | 429 | `POST /auth/signup`, `/auth/signup/resend` | Per-IP (5/h) or per-email (3/day) window exhausted; `Retry-After` says when. Fails **closed**: a down Redis refuses rather than allowing, because the alternative is an open mail relay aimed at addresses somebody else chose. |
| `password_policy` | 400 | `POST /auth/signup` | The password would be refused by the realm. `min_length` and `reasons[]` carry the specifics so the form can mark the field rather than showing a wall of text. Checked here, not left to Keycloak, so the message is one the product wrote. |
| `display_name_required` | 400 | `POST /auth/signup` | A name of only whitespace. Distinct from a 422 body so the form has a field to point at. |
| `signup_unavailable` | 503 | `POST /auth/signup` | Keycloak or the database refused. **Nothing was created on either side** — a database failure after the Keycloak user exists deletes it (`mdx_auth_signup_total{result=compensated}`). Safe to retry. |
| `code_invalid` | 400 | `POST /auth/signup/verify` | Wrong code; `attempts_left` counts down from 5. |
| `challenge_expired` | 400 | `POST /auth/signup/verify` | The code timed out (10 min) — **or** there is no pending signup for that address at all. One body for both, deliberately: distinguishing them would turn verify into the membership oracle `/auth/signup` refuses to be. |
| `challenge_consumed` | 400 | `POST /auth/signup/verify` | Already used, or superseded by a resend. |
| `too_many_attempts` | 429 | `POST /auth/signup/verify` | Five wrong codes spent the challenge. Ask for a new one. |
| `verify_retry` | 409 | `POST /auth/signup/verify` | The code was right and Keycloak could not be updated. **The challenge is not consumed** — the person keeps their code and retries in a moment. An outage that was not theirs must not cost them the code. |
| `email_not_verified` | 403 | `POST /auth/login` | A self-serve account that never confirmed its address. Keycloak answers a disabled account with the same `invalid_grant` a wrong password gets, so without this branch the person retypes a password that was never wrong. Show "confirm your email" and a resend button. Not an enumeration leak: reaching this branch requires having supplied the right password. |
| `origin_not_allowed` | 403 | any state-changing `/auth/*` from a web client | `Origin`/`Referer` is not in `CORS_ALLOWED_ORIGINS`. Native apps send `X-Client-Type: macos|ios` and no `Origin`. |
| `invalid_email` | 400 | `POST /auth/email/start` | The address is not syntactically an email. The only non-202 answer that depends on the input. |
| `rate_limited` | 429 | `/auth/email/start`, `/auth/email/verify` | Per-email or per-IP window exhausted; `Retry-After` says when. Same limits for known and unknown addresses. |
| `rate_limiter_unavailable` | 503 | `POST /auth/email/start` | Redis down and this scope fails closed; no code was sent. |
| `email_delivery_unavailable` | 503 | `POST /auth/email/start` | The mail provider failed within the send timeout; the challenge was deleted, ask for a new code. |
| `code_invalid` | 400 | `POST /auth/email/verify` | Wrong code; `attempts_left` in the problem extras. |
| `challenge_expired` | 400 | `POST /auth/email/verify` | The code's 10 minutes passed. Start again. |
| `challenge_consumed` | 400 | `POST /auth/email/verify` | Already used, superseded by a newer code, or exhausted. Start again. |
| `too_many_attempts` | 429 | `POST /auth/email/verify` | The fifth wrong code consumed the challenge. Start again. |
| `email_not_verified` | 403 | `POST /auth/login` | **BE-0.** The account exists and the password is right, but the address has not been confirmed. Distinct from `account_disabled` (nothing the person can fix) and from a 401 (wrong credentials): the way forward is the link already in their inbox, so a client shows the state and offers `POST /auth/signup/resend` rather than "wrong sign-in details". Not an enumeration oracle — it is only reachable *after* a correct password. |
| `use_password` | 409 | `POST /auth/email/verify` | **`dual` mode only.** The code was right, and the address belongs to an account that still lives in Keycloak, which cannot mint a session from one. Not an enumeration leak: possession of the mailbox is already proved by this point. Send the person to the password form with the address carried across. |
| `legacy_session` | 409 | `POST /auth/token` | **`dual` mode only.** The bearer is a Keycloak token, and auth-service cannot re-mint one for another `tid` without Keycloak's key — so switching workspace is a native-session capability for the duration (ADR-0047, recorded there up front). Clients disable the switcher for these sessions rather than letting the tap earn a 409; the way out is signing in with an emailed code, or switching in the web app. |
| `code_invalid` (MFA) | 400 | `POST /auth/mfa/verify`, `/auth/mfa/totp/confirm`, `/auth/reauth` | Wrong second factor, a TOTP code whose time step was already spent, or a used recovery code. `attempts_left` in the extras on the login challenge. |
| `challenge_expired` (MFA) | 400 | `POST /auth/mfa/verify`, `/auth/mfa/totp/confirm` | The five-minute login challenge or the fifteen-minute enrolment ran out. Start the sign-in again. |
| `too_many_attempts` (MFA) | 429 | `POST /auth/mfa/verify` | Five wrong second factors consumed the challenge; it also counts toward the account lockout. |
| `mfa_already_enabled` | 409 | `POST /auth/mfa/totp/enroll` | Disable the existing factor first. |
| `mfa_not_enabled` | 409 | `POST /auth/mfa/disable`, `/auth/mfa/recovery-codes` | Nothing to disable or regenerate. |
| `reauth_required` | 403 | any step-up endpoint | The session has not proved itself inside `AUTH_REAUTH_WINDOW_SECONDS`. Call `POST /auth/reauth/start`, then `POST /auth/reauth`. `reauth_window_seconds` in the extras. |
| `challenge_required` | 400 | `POST /auth/reauth` | `method: "email_code"` without the `challenge_id` from `/auth/reauth/start`. |
| `owner_reset_requires_owner` | 403 | `DELETE /auth/mfa/{sub}` | An admin may not strip an owner's second factor — that is an escalation path, not a helpdesk action. Another owner must do it. |
| `not_a_member` (MFA reset) | 403 | `DELETE /auth/mfa/{sub}` | You do not administer any workspace the subject belongs to. |
| `email_in_use` | 409 | `POST /auth/email/change/start|confirm` | Another identity already logs in with that address. Revealed deliberately: the caller is authenticated, so this is not an enumeration oracle, and hiding it would make the flow fail later with nothing to act on. |
| `email_unchanged` | 400 | `POST /auth/email/change/start` | The new address is the current one. |
| `sole_owner_with_members` | 409 | `POST /auth/account/delete` | You are the only owner of a workspace other people are still active in. `tenants[]` in the extras lists them; hand them over first. |
| `confirm_required` | 400 | `POST /auth/account/delete` | The body must carry `confirm: "DELETE"` exactly. |
| `session_revoked` (native) | 401 | step-up endpoints | The session row is gone or revoked. Sign in again. |
| `otp_required` | 401 | `POST /auth/login` | Enrolled account: send the TOTP code. |
| `otp_invalid` | 401 | `POST /auth/login` | Wrong TOTP code; retry. |
| `otp_unavailable` | 401 | `POST /auth/login` | MFA state inconsistent or the secret store is down; fail closed. |
| `mfa_enrolment_required` | 403 | MFA-gated routes | Enrol a second factor first. |
| `invalid_client` | 401 | `POST /auth/oauth/token` | IDX-B1b — unknown client id, wrong secret, expired or revoked secret, or a revoked credential. **Deliberately one body for all five**: telling them apart would let somebody enumerate which rooms exist. Also carries RFC 6749's `error: "invalid_client"`. |
| `unsupported_grant_type` | 400 | `POST /auth/oauth/token` | Only `client_credentials` is served here. |
| `client_rate_limited` | 429 | `POST /auth/oauth/token` | More than 60 grants a minute for one client id. A device should hold its token for ~15 minutes. |
| `client_locked` | 423 | `POST /auth/oauth/token` | Ten wrong secrets in ten minutes; locked for fifteen. `Retry-After` says how long. |
| `try_again` | 503 | `POST /auth/oauth/token` | Redis is unreachable so the lock cannot be checked. This endpoint fails **closed** — the one place in the program where availability yields, because the alternative is unlimited secret guessing. Retry after 5 s. |
| `rotation_in_progress` | 409 | `POST .../rotate` | The credential already holds two live secrets. Deploy or expire one first. |
| `personal_workspace` | 409 | `POST /tenants/{id}/devices` | A personal workspace has one member and no meeting room. |
| `model_not_configured` | 503 | `POST /v1/notes/{id}/ask` | No chat backend resolves in this environment. |
| `model_unavailable` | 503 | `POST /v1/notes/{id}/ask` | The model backend failed; `kind` names the failure class. |

IDX-B1b adds the `client_credentials` codes above. That endpoint answers in
two vocabularies at once: RFC 6749's `error` field, so a stock OAuth client
library reports something sensible, and this API's `code`, so everything
else can branch as usual.

IDX-A5 adds the MFA, step-up, email-change and deletion codes above, and
reuses `code_invalid` / `challenge_expired` / `challenge_consumed` /
`too_many_attempts` from IDX-A3 — the second-factor challenge is the same
kind of object as an emailed code, and a client that already handles those
four needs no new branches for the common cases.

Two responses that are NOT errors and are easy to mistake for one:
`POST /auth/email/verify` answering `200` with `status: "mfa_required"`
and an empty `access_token` is a success — the first factor passed, and
the client must complete `POST /auth/mfa/verify`. And every native route
answers `404` rather than `503` when the deployment is in Keycloak mode
or has no mail relay, so a prober learns nothing about what is switched
off.

IDX-A3 adds `invalid_email`, `rate_limited`, `rate_limiter_unavailable`,
`email_delivery_unavailable`, `code_invalid`, `challenge_expired`,
`challenge_consumed`, `too_many_attempts`, and extends `account_disabled` /
`no_workspace` to `POST /auth/email/verify`.

`email_not_verified` is BE-0's, and the only auth answer this app treats as
information rather than as a refusal: it is the one failure whose remedy is
neither "try again" nor "ask an administrator" but "go and read your mail".
`POST /auth/signup/resend` is its partner and answers the same way for every
address, known or not, for the reason `/auth/email/start` does.

`use_password` and `legacy_session` belong to the cut-over rather than to a
sprint: both exist only while `MDX_IDP_MODE=dual`. `use_password` is the
one answer from `/auth/email/verify` that is neither a session nor a
refusal — it is a redirection to the other way in. `legacy_session` is the
one capability the period takes away rather than adds. Clients handle both
before the cut-over serves them, because the alternative is a deployment
mode that bricks sign-in for every pre-existing account until the clients
catch up. The iOS app does, as of IOS-1 (`ios/Sources/NotesAICapture/Models.swift`,
`APIError.isUsePassword` / `.isLegacySession`).

A note on what `/auth/email/start` does NOT return: there is no code for
"unknown address", "account locked" or "undeliverable mailbox". All three
answer 202 with the same body as a successful send — the endpoint is an
enumeration dead end by construction, and a code that distinguished them
would undo that. A malformed address (`invalid_email`, and pydantic's own
422 before it) is the single input-dependent answer.

IDX-A2 introduces `auth_refresh_replay` (already in use), `session_expired`,
`no_refresh_token`, `session_revoked`, `account_disabled`, `not_a_member`,
`membership_suspended`, `no_workspace`, `origin_not_allowed`.

IDX-M1 carries the session routes A2 left undelivered, so in **native mode**
`auth_refresh_replay`, `session_expired`, `no_refresh_token`,
`account_disabled` and `no_workspace` are served by
`routers/session_native.py` on `POST /auth/refresh` and `POST /auth/logout`.
IDX-M2 carries the last of that surface: `POST /auth/token` serves
`not_a_member`, `membership_suspended`, `tenant_dissolved`,
`account_disabled` and `session_revoked`, and is the only path on which a
token's `tid` changes.
In keycloak mode `/auth/refresh` is still Keycloak's (`routers/login.py`)
and answers `auth_refresh_replay`, `session_expired` and
`no_refresh_token`. Keycloak reports an expiry and a replay with the same
`invalid_grant`; the router tells them apart by the presented token's own
`exp`, so an idle client past `ssoSessionIdleTimeout` gets
`session_expired` and keeps the rest of its sessions. Those three paths
also honour the `X-Client-Type` transport split, so a native client's
refresh token is in the body there too.

## BE-0 — self-serve signup

`signup_rate_limited`, `password_policy`, `display_name_required`,
`signup_unavailable`, `code_invalid`, `challenge_expired`,
`challenge_consumed`, `too_many_attempts`, `verify_retry` and
`email_not_verified` belong to `POST /auth/signup`, `/auth/signup/verify`,
`/auth/signup/resend` and the `/auth/login` branch. They exist only where
Keycloak still mints tokens (`MDX_IDP_MODE` `keycloak` or `dual`) and only
when `MDX_SIGNUP_ENABLED` is set; otherwise the routes answer 404.

Two of them describe an outcome the client must not treat as failure:

* **`/auth/signup` answers `202` for an address that already has an
  account.** There is no code for "already registered", on purpose. The
  body, the status and the amount of work done are identical for both
  branches, so the endpoint cannot be used to test whether an address is
  a customer. The person is told which happened by the mail they receive
  — `signup_verify` carries a code, `signup_exists` carries a sign-in
  link — and reading either requires already controlling the mailbox.
* **`/auth/signup/resend` answers `202` for an address with nothing
  pending.** Same reason.

All of these retire with BE-0 itself: BE-3's `/auth/email/*` replaces
password signup once `MDX_IDP_MODE=dual` is switched on fleet-wide
(ADR-0047), and `use_password` / `legacy_session` above are that period's
codes.

## note-service — reading somebody else's note

Note reads carry no `code`; the client branches on the problem `type`.

| Type | Status | Where | Meaning / client action |
| --- | --- | --- | --- |
| `https://errors.notes-ai/missing-read-purpose` | 422 | `GET /v1/notes/{id}`, `/versions`, `/versions/{n}`, `/pdf`, `/audio`, audio clips | The caller may see the note but is not on its author team and was not shared it — a workspace admin or auditor on anything, a member on a `workspace`-visible note — and sent no `?purpose=`. `allowed` lists the values (`review`, `audit`, `legal`, `export`, `collaboration`). Retry **once** with a purpose (the apps use `review` to open, `export` for the PDF); the server records it in the audit trail and the envelope then carries `primary_author_name`, so say whose note is being shown. A note the caller may not see at all is a 404 before this check, never a 422. |
