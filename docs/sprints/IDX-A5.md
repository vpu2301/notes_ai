# IDX-A5 — MFA, session management, email change, account deletion, issuer cut-over

**Status:** feature scope delivered (2026-09-05). The cut-over is **written
and not executed** — see §"Cut-over".
**Branch:** S01 (uncommitted working tree).

## Deviations, decided up front

Three things in the pack did not survive contact with the repo. All three
were put to the user before any code was written; the answers are recorded
here because each one changes the contract.

| Pack says | Delivered | Why |
| --- | --- | --- |
| F1: build `libs/crypto` as a new, tiny AES-256-GCM helper keyed by `AUTH_SECRETS_KEKS_JSON` | Reused the **existing** `libs/crypto` envelope (master key → tenant KEK → per-object DEK) via a thin adapter, `domain/identity_secrets.py` | `libs/crypto` already exists, is tested, is the ADR-0011 sanctioned path, is what `auth_service.totp` already packs TOTP secrets through, and a CI gate (`check-no-crypto`) forbids reaching for `cryptography.hazmat` anywhere else. A second key hierarchy would mean two rotation stories and two failure modes. |
| `POST /auth/mfa/verify` = the login challenge | Same — and the sprint-16 meaning ("complete my enrolment") moved to `POST /auth/mfa/totp/confirm`, which the pack defines anyway | `main.py` mounts the sprint-16 router in keycloak mode and the native one in native mode, so the path never means two things in one process and no client breaks before cut-over. |
| §F7/N.7: execute the cut-over on staging and production | Runbook + smoke checklist + rollback written (`docs/runbooks/idx-issuer-cutover.md`); **not run** | Flipping a production IdP is an operator action with a live blast radius, and the pack itself defers one of its decisions ("MFA-enrolled pilot users… decided by the founder"). The runbook has a Run log section to fill in. |

Two more, smaller, decided while building:

* **A4 is missing**, and A5 gates eight endpoints on "recent auth". The
  minimum A4 slice is included: `auth_sessions.last_authenticated_at` plus
  `POST /auth/reauth/start|reauth`. For an MFA user the step-up is their
  authenticator; for everyone else it is a code mailed to the address on
  the account, because until A4 there is no password to ask for. A4 adds
  the password as a third method and nothing else here changes.
* **`auth.mfa_enrolled` → `auth.mfa.enrolled`.** The catalogue already had
  the dotted name from sprint 16, and the house rule (recorded next to
  `USER_RESET_MFA`) is that the existing name wins. A5 reuses it and adds
  `auth.mfa.disabled` / `.failed` / `.challenged` /
  `.recovery_code_used` / `.recovery_codes_regenerated` in the same style.
  Renaming would have split one account's MFA history across two kinds.

## Inspect-first findings

| Item | Finding |
| --- | --- |
| `libs/crypto` | Full envelope hierarchy, `Envelope.encrypt/decrypt(tenant_id, aad)`, `TenantKekRepository.get_or_create`. Keys on a **tenant**, and an identity has none — identity secrets are therefore wrapped under the **platform tenant's** KEK, recorded per row in `identity_totp.kek_tenant_id` so a re-key never guesses. |
| `auth_service/totp.py` | Sprint-16 RFC 6238 in pure stdlib (no `pyotp`), plus `encrypt_secret`/`decrypt_secret` envelope packing with AAD bound to the subject. Reused wholesale; added `matching_step()` because the pack's replay rule needs "valid **for when**", not just "valid". |
| `routers/mfa.py` | Keycloak-attribute store. `POST /auth/mfa/verify` already meant "complete enrolment" — the collision above. |
| `deps.current_user` | Verified against `settings.auth_issuer` (Keycloak) and the JWKS cache held only Keycloak's URL. **In native mode auth-service could not verify its own tokens**, so every bearer-authenticated A5 endpoint would have 401'd. Fixed by `build_jwks_cache`. |
| `password.py` | Every endpoint reaches Keycloak, and its `GET /auth/sessions` collided with the new one. Mounted in keycloak mode only. |
| `users` RLS | `users_writer_tenant` is scoped to `app.tenant_id` even for `tenant_writer`, unlike `tenants`/`tenant_memberships`. `change_email` therefore sets the scope per membership before mirroring the address. |
| `pii_filter` | Already scrubs `recovery_code` / `recovery_codes`. Nothing to add. |
| `EmailStr` | Rejects the reserved `.test` TLD; integration fixtures use `.example`. |

## Delivered

1. **Migration `0025_idx_mfa_and_account`** — `identity_totp`,
   `identity_recovery_codes` (both `tenant_writer`-only, RLS ENABLE+FORCE,
   no `app_role` grant and no `app_role` policy); `auth_challenges.metadata`
   plus the kinds `totp_enroll`/`mfa_login`/`email_change`/`reauth`;
   `auth_sessions.last_authenticated_at`/`device_name`/`revoked_reason`;
   `identities.locale`/`timezone`.
2. **`domain/mfa.py`** — recovery-code alphabet (base32 minus O/I), shape,
   normalisation, hashing; `decide_step` (the replay rule) as pure
   arithmetic.
3. **`domain/identity_secrets.py`** — `EnvelopeSecretBox`, the adapter onto
   `libs/crypto`; the envelope is resolved on first use, so a deployment
   where nobody enrols never needs the master key mounted.
4. **`domain/mfa_service.py`** — `challenge_if_required` (the first-factor
   gate every login path passes through), `verify_login_challenge`,
   enrolment/confirm/disable, recovery-code issue and spend. The
   enrolment secret lives in `identity_totp` with `confirmed_at IS NULL`
   rather than in challenge metadata: one encrypted home, and an
   unconfirmed row gates nothing.
5. **`domain/account_service.py`** — step-up, sessions list/revoke with
   `/24` IP masking, email change with the 24-hour revert token, deletion
   with the sole-owner rule.
6. **Routers** — `mfa_native.py` (challenge verify, enrol, confirm,
   disable, recovery codes, admin reset), `account.py` (reauth, sessions,
   email change + revert page, deletion, `PATCH /auth/me`),
   `native_common.py` (the `recent_auth` dependency, problem mapping,
   `current_identity`).
7. **Mail** — five new kinds × three languages (`mfa_enabled`,
   `mfa_disabled`, `recovery_code_used`, `email_changed`,
   `account_deletion_scheduled`), generated from the house skeleton so the
   layout cannot drift from `auth_code.*`. Only `email_changed` carries a
   link, and it masks the new address.
8. **`domain/mailing.py`** — the render-and-send primitive, extracted so
   A3's `CodeMailer` and A5's `SecurityMailer` share one timeout and one
   pair of metric instruments.
9. **Scripts** — `scripts/ops/idx-purge-deleted-identities.py`
   (`--dry-run`/`--apply`, one transaction per identity, idempotent) and
   `scripts/ops/idx-rekey-totp-secrets.py`.
10. **Docs** — `docs/runbooks/idx-issuer-cutover.md`, fifteen new rows in
    `error-codes.md` (plus a note on the two 200s that look like errors),
    ten new audit kinds in `event-kinds.md`, `AUTH_REAUTH_WINDOW_SECONDS`
    in `.env.example`.

### Two bugs the tests found

* **Signing in during the deletion grace period returned 409.**
  `request_deletion` dissolves the workspaces nobody else is in;
  `reactivate` restored only the identity, so the user came back to an
  account with no active membership — no `tid`, no token. `reactivate` is
  now symmetric with the dissolve, which is also what the deletion mail
  promises ("restores your account exactly as it was").
* **A recovery-code alphabet edge.** `9` is not in base32, so a code
  containing one normalises short and matches nothing. Correct behaviour,
  but the first version of the test asserted otherwise; the rule is now
  pinned explicitly, including that O and 0 collapse together (neither can
  appear in a real code, so collapsing them spares a user a failed attempt
  for reading a letter as a digit).

### One pre-existing gate fixed

`make check-no-crypto` was **already failing** before this sprint: IDX-A2
added RSA signing-key handling in four files without extending the
allowlist. Added, with the reasoning — an RS256 signer parses PKCS#8 and
serialises JWKs, which is not data-at-rest crypto and has no `libs/crypto`
API. The gate is green again.

## Verification

* auth-service unit: **273 passed** (25 new in `test_mfa_domain.py`, plus
  the extended mail-render gate).
* Integration against the dev Postgres + Redis + the real envelope
  (`RUN_DB_INTEGRATION=1`): **48 passed** — 17 in `test_mfa_account_db.py`
  and 16 in `test_mfa_account_e2e.py` are new.
* Migration `0025` applies and rolls back cleanly.
* `mypy --strict` on the ten new modules: clean apart from the repo-wide
  `import-untyped` noise (no `py.typed` anywhere in `libs/`).
* `check-rls` (39 tables), `lint-imports`, `check-metric-names`,
  `check-audit-insert`, `check-no-os-environ`, `check-no-crypto`, ruff:
  green. auth-service OpenAPI snapshot unchanged (native routes are
  native-mode only; the dump runs in keycloak mode).
* `make openapi-check` still fails on `note-service-openapi.json` — the
  unrelated, pre-existing Ask-feature drift, already `M` before IDX-A3.

## Acceptance criteria

| Criterion | Proven by |
| --- | --- |
| Once MFA is on, no login path yields a session without a valid TOTP or recovery code | `test_once_mfa_is_on_the_email_code_path_yields_no_session` (real app, real DB) |
| A TOTP code is accepted at most once | `test_a_totp_code_is_accepted_at_most_once`, `test_the_code_that_confirmed_enrolment_cannot_also_sign_you_in`, `test_a_time_step_is_claimed_exactly_once` (10 concurrent uses → 1 winner) |
| TOTP secrets in the DB are AES-GCM ciphertext with a key id; a test reads the column and asserts it is not base32 | `test_the_stored_totp_secret_is_ciphertext_not_base32` |
| Changing email to X requires a code delivered to X; the old address gets a revert link that restores it and revokes all sessions | `test_the_email_change_needs_a_code_sent_to_the_new_address`, `test_the_old_address_can_undo_the_change_and_everything_is_revoked` |
| The only owner of a workspace with other members cannot delete their account | `test_the_sole_owner_of_a_shared_workspace_cannot_delete`, `test_the_only_owner_of_a_shared_workspace_is_refused` |
| Cut-over completed with the smoke checklist green | **Not met — not executed.** Runbook and checklist written. |

## Cut-over

Not run. `docs/runbooks/idx-issuer-cutover.md` has the preconditions, the
fleet-first ordering (repoint every other service, flip auth-service
last), the smoke checklist, and what rollback costs — notably that
rolling back signs out everyone who signed in after the flip, that
identities created after it have no Keycloak user, and that migration
0025 must **not** be rolled back because its down-migration destroys every
enrolled second factor.

Two things need a human decision before the window:

1. **MFA-enrolled pilot users.** Current macOS/iOS clients send no
   `X-Client-Type`, so the origin check treats them as browsers and
   refuses their `/auth/*` POSTs; they also call `/auth/login` with a
   password, which has no native implementation until IDX-A4. The pack
   assigns this to the founder — tell them to use the web flow, or keep
   MFA off until M1/I1.
2. **Whether to accept losing `/auth/password/*` in native mode.** It is
   Keycloak-backed end to end, so it cannot work after the flip; IDX-A4
   restores it natively.

## Not delivered / next

- The rest of IDX-A2's session surface: `refresh`, `logout`,
  `/auth/token`, the `/auth/me` extension. Sessions are created, listed
  and revoked; nothing rotates them, so a native deployment's users stay
  signed in for `AUTH_REFRESH_TTL_SECONDS`.
- IDX-A4: passwords, the 423 `account_locked` response, the Keycloak
  credential import, and password as a third step-up method.
- `auth.account_purged` is described in the catalogue and the purge script
  prints the reminder, but the script does not write it (libs/audit owns
  that table and the script has no service context). Wire it when B3
  schedules the job.
- Passkeys, trusted devices, org MFA policy, SMS: NOT NOW (pack).

## Debt / NOT-NOW

- The sprint-16 `routers/mfa.py` and `routers/password.py` are dead code
  in native mode. B2 removes them with Keycloak.
- `docs/audit/permissions.csv` has not been checked for the new kinds.
- The step-up window is global (`AUTH_REAUTH_WINDOW_SECONDS`). A
  per-operation window (longer for a profile edit, shorter for deletion)
  is a reasonable later refinement.
- Recovery-code count is fixed at ten; no "you are running low" reminder
  exists beyond the per-use mail.
