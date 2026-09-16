# BE-0 — Self-serve signup on the current stack

**Track:** Backend · **Date:** 2026-09-06 · **Status:** delivered (unmerged working tree)
**Unblocks:** OPS-0 (live), WEB-0, MAC-0, IOS-0

Keycloak stays the identity provider. An account is created through the
admin client with a password already set and `enabled=false`; a six-digit
code proves the address; verification enables it. From then on the person
signs in with `POST /auth/login` exactly like every existing user — web,
macOS and iOS, no client change.

## Inspect-first findings

| Item | Finding |
| --- | --- |
| `keycloak_client.create_user` | Sets `requiredActions: ["UPDATE_PASSWORD"]` and no credentials, as the brief said. BE-0 adds `create_user_with_password` rather than a flag: the differences (no required actions, a credential in the create payload, `enabled=false`, two realm roles) are the method. |
| `admin.py › invite_user` | The DB half was copied, not the route. `users.status='invited'` is the pre-verification state; the CHECK already allows it. |
| Password recovery slice | `domain/email_code.py` (code, hash, the verify state machine, `evaluate`), `adapters/email.py`, `domain/compose.py` + `copy.py`, `domain/mailing.py` — all reused unchanged. `OnboardingService` adds orchestration, not machinery. |
| `routers/login.py` | Maps Keycloak `400 invalid_grant` to 401, and "Account is not fully set up" / "account is locked" to 423. BE-0 adds one branch before the 401. |
| Realm password policy | **The realm has no `passwordPolicy` configured.** `domain/password_policy.check_password` is the only thing that bites, so the API check is not a mirror — it is the policy. Recorded because the brief assumed otherwise. |
| `auth_challenges.kind` | A new `signup_verify` value (migration `0032_be0_signup_verify`, written by a parallel session and adopted here). |

## Deltas to the brief

1. **The account gets an `identities` row too.** The brief's step 2 lists
   `tenants` + `users` + `tenant_memberships`. The identity is written in
   the same transaction, with `id = <Keycloak sub>` (the convention
   migration 0027 established) and `legacy_idp = true`. Without it a BE-0
   account is second-class: `/auth/me` cannot describe the person, the
   `check-identity-bridge` gate has nothing to pair, and BE-3's email-code
   login cannot find them when `dual` is switched on. It costs one
   statement in a transaction that was already open.

2. **Both realm roles, not one.** `[tenant_admin, member]`. S14's
   admin/content separation gives `tenant_admin` no content permission at
   all, so an account holding it alone signs in and then gets
   `403 … cannot 'asr.write'` on the first recording. The brief's §D says
   `[tenant_admin, member]`; this note exists because the *native* path
   had the same bug and BE-3's first-use test is what found it.

3. **`timezone` is `Europe/Kyiv`**, per the brief. `locale` comes from
   `Accept-Language` when it is `en`/`de`/`uk`, else `en`.

4. **Lookups read `identities`, not `users`.** `users` is RLS-scoped per
   tenant and its policy casts `current_setting('app.tenant_id')` to a
   UUID — with nothing set that cast *raises* rather than matching no
   rows. Signup, verify and the login branch all run without a token, so
   they have no tenant to set. `identities` is person-level and readable
   under a permissive policy. `email_verified_at IS NULL` is the marker
   for "never confirmed".

## What shipped

| Piece | Where |
| --- | --- |
| `create_user_with_password`, `set_email_verified`, `delete_user`, `split_display_name` | `keycloak_client.py` |
| `OnboardingService` (signup / verify / resend / `create_account`), compensation, rate limits, metrics | `domain/onboarding_service.py` |
| `SignupMailer` | `domain/signup_mailer.py` |
| `POST /auth/signup`, `/verify`, `/resend` | `routers/signup.py` (mounted in `keycloak` and `dual`) |
| `403 email_not_verified` branch | `routers/login.py` |
| Concierge CLI | `ops/onboard.py` |
| Stale-signup cleanup | `ops/cleanup_invited.py` + migration `0033_signup_cleanup_grants` |
| Copy + 9 HTML templates (`signup_verify`, `signup_exists`, `concierge_welcome` × en/de/uk) | `domain/copy.py`, `adapters/templates/` |
| Settings (`MDX_SIGNUP_ENABLED` + 11 more) | `config.py`, `.env.example`, `docker-compose.override.yml` |

## Two bugs only a live Keycloak could find

Both were invisible to the unit suite, because a fake does not implement
Keycloak's rules. Both are recorded in `docs/runbooks/auth.md § Signup`.

**1. An empty `lastName` makes the account unusable.** The realm's
declarative user profile marks `firstName` and `lastName` required. A user
created with `lastName: ""` gets `VERIFY_PROFILE` demanded at
*authentication* time — not at creation — and the password grant refuses
with "Account is not fully set up". The user record shows
`requiredActions: []` throughout, which is what makes it expensive to
diagnose: it is the same message a pending required action produces, and
the record says there is none. `split_display_name` writes a single-word
name to both fields.

**2. `tenant_id` was silently dropped, so tokens had no `tid`.**
Keycloak 24+ ships declarative user profiles with unmanaged attributes
disabled: an attribute the profile does not name is discarded on every
admin-API write, without an error. `tenant_id` feeds the
"tid (tenant_id user attribute)" protocol mapper, and `tid` is the claim
every service in the fleet filters rows by — so the token verified as
`MalformedClaims` and `/auth/login` returned 200 with an empty
`tenant_id`. **This affected the existing admin-invite path too**, not
just signup; realm *import* bypasses the profile, so the seeded dev users
work and nothing showed it until a user was created at runtime. Fixed by
declaring `tenant_id` and `mfa_enrolled_at` in the
`components → org.keycloak.userprofile.UserProfileProvider` block of
`infra/keycloak/realm-export.json`, admin-writable only (a user-editable
`tenant_id` would be a tenancy bypass).

## Verification

Against the live dev stack (real Keycloak, real Postgres, real Redis,
Mailpit):

* `tests/integration/test_signup_e2e.py` — 7 tests: signup → verify →
  login with `tid` and both roles; login before verify is
  `403 email_not_verified`; a second signup creates nothing and sends the
  other mail; the created Keycloak user has no required actions; verify
  enables it; five wrong codes then a resend; the API refuses what the
  realm would.
* `tests/unit/test_signup_routes.py` — 24 tests, no container: the
  uniform 202, the compensation path (a database failure deletes the
  Keycloak user), the rate-limit subject being a hash rather than the
  address, the challenge-bound code hash.
* **The concierge CLI was run for real.** It created
  `ada.lovelace@concierge.example` in Keycloak, mailed a 20-character
  password through Mailpit, and that account then signed in and read 15
  templates from note-service and `GET /asr/jobs` — the first-use check.
  `check-identity-bridge` green throughout.
* The cleanup CLI removed the unconfirmed account and left the confirmed
  one, after migration 0033 granted the four DELETEs it needs.

## Not done

* **`docs/api/auth-service-openapi.json` not regenerated.** `make
  openapi-dump` needs the service running with `MDX_SIGNUP_ENABLED=true`;
  the committed snapshot is from a deployment without it, so the routes
  are absent. Run it before merging or `make openapi-check` will drift.
* **No mail relay.** Everything above is Mailpit. FND-2's provider, SPF,
  DKIM and DMARC are outstanding, and OPS-0 cannot onboard a real
  external user until they are.
* **CAPTCHA** stays NOT NOW. The signal to pull it forward is a sustained
  burst on `mdx_auth_signup_total{result=rate_limited}`.
* **Terms-of-service acceptance** — legal decides; a boolean column and
  one line in `_write_account_rows` when they do.
* **`/auth/me` still returns `identity: null` in `keycloak` mode**, even
  though BE-0 now creates the row. `_identity_and_memberships` is gated on
  `account_services`, which is native/dual only. Clients fall back to
  `db_user`, as `routers/me.py` already documents. Worth revisiting when
  `dual` goes on.
