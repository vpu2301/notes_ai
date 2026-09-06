# Runbook — IDX issuer cut-over (Keycloak → native)

**Status:** not executed. Written in IDX-A5; the pack assigns execution to
the sprint, but flipping a production identity provider is an operator
action with a live blast radius, so this is the procedure and the checks,
not a record of a run. Fill in the "Run log" section when you do it.

**Owner:** whoever holds the deploy. **Window:** low-traffic, with a
second person watching dashboards. **Expected duration:** 20 minutes for
staging, 20 for production, plus a 24-hour soak between them.

---

## 0. What the flip actually does

`MDX_IDP_MODE=native` changes three things at once:

1. **auth-service starts signing its own tokens.** `AUTH_SIGNING_KEYS_JSON`
   must be set, or the service refuses to start (deliberately — an issuer
   that cannot sign is not a degraded issuer, it is no issuer).
2. **The native routes appear and the Keycloak-backed ones go.** Native
   mode mounts `/auth/email/*`, `/auth/mfa/*` (the IDX-A5 meanings),
   `/auth/sessions*`, `/auth/reauth*`, `/auth/account/delete`,
   `PATCH /auth/me`, and the discovery/JWKS documents. It stops mounting
   the sprint-16 `/auth/mfa/enrol|verify` pair and the whole
   `/auth/password/*` router, because every endpoint in those reaches
   Keycloak.
3. **Every other service must be repointed.** They verify `iss` against
   `AUTH_ISSUER`; a token signed by auth-service fails until they are
   told to expect it.

Step 3 is the one that takes the fleet down if it is done in the wrong
order. **Repoint the fleet first, flip auth-service last** — the
discovery and JWKS documents are served in native mode only, so there is
a moment where the other services must already trust an issuer that is
not yet issuing. That is fine: they cache nothing until a token arrives.

## 1. Preconditions

- [ ] Migrations `0024` and `0025` applied (`make migrate-status` shows no
      pending). The native tables do not exist without them.
- [ ] `AUTH_SIGNING_KEYS_JSON` present in the secret store for the target
      environment. Generate with `scripts/ops/gen-signing-key.py --list`.
      **Never** `AUTH_SIGNING_KEYS_FILE` outside dev — the service refuses
      it when `ENVIRONMENT=production`.
- [ ] `MDX_MASTER_KEY_PATH` (or the Vault transit config) reachable —
      IDX-A5 stores TOTP secrets through `libs/crypto`, and the first
      enrolment builds the envelope. A deployment with no second factors
      yet will not notice a missing master key until somebody enrols, so
      check it now rather than discovering it from a support ticket.
- [ ] `AUTH_PLATFORM_TENANT_ID` matches the seeded row
      (`00000000-0000-0000-0000-0000000000f1` unless overridden). Audit
      events with no customer go here; a wrong id fails the audit write,
      not the request, so it will be quiet.
- [ ] A mail relay is configured (`MDX_EMAIL_PROVIDER=smtp` and the SMTP
      settings). Native mode with no provider builds neither the
      email-code service nor the account surface, and every one of those
      routes answers 404 — which looks exactly like a bad deploy.
- [ ] Redis reachable. `/auth/email/start` fails **closed** without it.
- [ ] `CORS_ALLOWED_ORIGINS` lists the real SPA origin. The origin check
      middleware is native-mode-only and will 403 browser POSTs otherwise.

### The known client gap — decide before you start

Today's macOS and iOS apps, and the smoke scripts, send **no**
`X-Client-Type` header and no `Origin`. The origin check treats a client
with neither as `web` and refuses its state-changing `/auth/*` calls.
Until M1/I1 ship the header, either:

- keep those clients on a deployment that has not cut over, **or**
- add their origin to `CORS_ALLOWED_ORIGINS`, **or**
- accept that native apps cannot sign in during the window.

The same clients call `/auth/login` with a password, which after cut-over
has no native implementation until IDX-A4. **Pilot users with MFA enabled
cannot use the current native apps at all** — the pack flags this as a
founder decision. Record which way it went in the run log below.

## 2. Staging

1. Repoint every non-auth service:
   `AUTH_ISSUER=<AUTH_ISSUER_URL>` and
   `AUTH_JWKS_URL=<AUTH_ISSUER_URL>/.well-known/jwks.json`.
   Roll them. They keep working — nothing is issuing native tokens yet.
2. Set `MDX_IDP_MODE=native` on auth-service and roll it.
3. Confirm it came up as an issuer, not just alive:
   ```
   curl -s $AUTH_ISSUER_URL/.well-known/openid-configuration | jq .issuer
   curl -s $AUTH_ISSUER_URL/.well-known/jwks.json | jq '.keys[].kid'
   ```
   The `kid` must match the active key. An empty key list means the key
   list parsed but every entry is past `not_after`.
4. Run the smoke checklist (§4).
5. Soak 24 hours. Watch `mdx_auth_otp_start_total{result="sent"}` rising
   and `{result="limiter_unavailable"}` flat.

## 3. Production

Same three steps. Do not skip the fleet-first ordering, and do not batch
the auth-service roll with anything else — if something goes wrong you
want exactly one variable to undo.

## 4. Smoke checklist

Run against the target environment; every line must pass before the
window is called done.

- [ ] `POST /auth/email/start` with a **new** address → `202` with
      `challenge_id`, `expires_in: 600`, `resend_after: 60`.
- [ ] The code arrives. Subject contains no digits.
- [ ] `POST /auth/email/verify` → `200`, `is_new_identity: true`, a
      `memberships[0].kind == "personal"`, and an `access_token` whose
      `iss` is `AUTH_ISSUER_URL`.
- [ ] `SELECT count(*) FROM tenants WHERE kind='personal'` incremented by
      exactly 1.
- [ ] The same token reads and writes a note in note-service — this is
      the check that proves the fleet was repointed correctly.
- [ ] `POST /auth/email/start` with a **known** address returns a body
      byte-identical to the unknown-address case except `challenge_id`.
- [ ] `GET /auth/sessions` lists the session, `current: true`, `ip_last`
      ending `/24`.
- [ ] `POST /auth/reauth/start` → `email_code`; complete it → `204`.
- [ ] `POST /auth/mfa/totp/enroll` → secret + `otpauth_uri`; confirm with
      a code → ten recovery codes.
- [ ] Sign in again → `status: "mfa_required"` with **no** access token.
- [ ] `POST /auth/mfa/verify` with the authenticator's next code → `200`.
- [ ] `SELECT secret_enc FROM identity_totp LIMIT 1` is not base32.
- [ ] `make check-rls` and an audit chain verification
      (`GET /auth/audit/verify`) both green.
- [ ] No log line in the window contains an email address or a code.

## 5. Rollback

Set `MDX_IDP_MODE=keycloak` on auth-service, roll it, then repoint the
fleet's `AUTH_ISSUER`/`AUTH_JWKS_URL` back to Keycloak and roll them.

What rollback costs, and why you should verify the restore on staging
before you need it in production:

- **Every native session dies.** `auth_sessions` rows survive, but
  Keycloak-mode `current_user` will not accept a native token, so
  everyone signed in after the cut-over is signed out.
- **Identities created after the cut-over have no Keycloak user.** They
  cannot sign in at all until you either cut over again or create them in
  Keycloak by hand. Note their addresses before rolling back.
- **Do not roll back migration 0025.** Its down-migration drops
  `identity_totp`, which destroys every enrolled second factor; re-applying
  it later leaves those users needing an admin MFA reset. Schema and mode
  are independent — leaving 0024/0025 applied in keycloak mode is inert.

## 6. Run log

Fill in when executed.

| Field | Value |
| --- | --- |
| Staging cut-over at | |
| Staging soak result | |
| Production cut-over at | |
| Smoke checklist | |
| MFA-enrolled pilot users: decision | (told to use web / MFA kept off / other) |
| Rollback rehearsed on staging | |
| Issues seen | |
