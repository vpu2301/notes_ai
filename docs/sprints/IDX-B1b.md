# IDX-B1b — Non-human principals: service & device credentials

**Status:** delivered (2026-09-05). Production room re-provisioning is an
operator task and is **not** done — see §"Before B2".
**Branch:** S01 (uncommitted working tree).

## The finding that reframes this sprint

The pack's premise is that ambient capture "breaks at Keycloak removal".
It is already broken, and has been. A real `room-device-demo` token,
captured from the running dev realm, is **rejected by `libs/auth.Claims`
on four counts**:

```
sid            Field required
clientHost     Extra inputs are not permitted
clientAddress  Extra inputs are not permitted
client_id      Extra inputs are not permitted
```

`POST /asr/jobs` runs `requires("asr.write", "asr_job")` → `current_user`
→ `Claims(**payload)`, so a Keycloak-provisioned room cannot call the API
at all. The captured payload is checked into
`tests/unit/test_client_credentials.py` and the rejection is asserted, so
this is verifiable rather than a claim in a document.

Two consequences:

1. **B1b does not preserve the device path; it is the first time that
   path can work.** Worth knowing before anyone counts on ambient capture
   in production today.
2. **The claims-parity test cannot mean what the pack says it means.**
   Byte-parity with the captured token would reproduce a token the fleet
   rejects. Parity is measured instead against the shape `Claims`
   accepts: same `sub`/`tid`/`roles`/`aud`/`typ`, plus the `sid` Keycloak
   omits, minus the Keycloak bookkeeping the model forbids.

## Inspect first

| Item | Finding |
| --- | --- |
| Clients with `serviceAccountsEnabled` | `mdx-backend`, `mdx-admin`, `mdx-asr-worker`, `mdx-dictation`, `room-device-demo`. |
| Service-account **users** in the realm | Only two: `service-account-mdx-admin` (no realm roles, no attributes — Admin API only, retired by the pack) and `service-account-room-device-demo` (`roles=['device']`, `tenant_id`=tenant A). `mdx-backend`, `mdx-asr-worker` and `mdx-dictation` have **no service-account user at all**. |
| What their tokens actually contain | Captured live. `mdx-asr-worker` and `mdx-backend` get `roles: ["offline_access","default-roles-notes","uma_authorization"]` — Keycloak defaults, **not** `service` — and **no `tid`**. Neither can pass `Claims` either. |
| Runtime consumers | None. `grep -rn "client_credentials\|mdx-asr-worker\|mdx-dictation\|service-account" services libs scripts` finds only auth-service's own Keycloak **admin** client and a comment in `dictation-service/ws/handler.py:265` reading "the old service-account plumbing never existed". |
| ⇒ Conclusion | The three service clients are declared-but-unused. Per the pack's own rule ("only runtime consumers get credentials"), **no service credentials are seeded**. Only the device is. |
| `libs/auth` `Claims` | `tid: UUID` and `sid: str` are both **required**, no defaults. This collides with F1's `tenant_id IS NULL for service` — see the decisions below. |
| `TokenService.mint` | Requires a non-empty `session_id` and a `tenant_id`. Used unchanged. |
| `device` grant set | `docs/auth/permissions.csv`: `asr.write/read`, `dictation.start/read/finalize`, `tenant.read`. Unchanged by this sprint — only the provisioning procedure changes. |

## Decisions the pack left colliding

| Question | Answer |
| --- | --- |
| `Claims.tid` is required but a service credential has no tenant | Service tokens are minted against the **platform tenant**. It owns no customer data, so a leaked service token reaches nothing — the right default for a principal nobody has scoped. The table keeps the pack's `service ⇒ tenant_id IS NULL` CHECK; only the minting rule fills the gap. A future S2S consumer needing a customer tenant is a new decision, not a silent default. |
| `Claims.sid` is required but a client credential has no session | `sid = the credential id`, so `sid == sub`. Honest (there is exactly one "session" per credential, forever) and useful: a denylist push on **either** key revokes it. |
| No "platform owner" role exists in the matrix | `/admin/credentials` requires `tenant_admin` **and** `tid == platform tenant`. Both halves: the role alone would let any workspace admin mint platform credentials; the tenant alone would let any platform-tenant member do it. |
| IDX-B1 (the `device.manage` policy) has not been run | The pack's "cut first" option was to drop `/tenants/{id}/devices`. They are built instead, gated on the same explicit owner/admin membership check IDX-A5 uses for admin MFA reset, with the `device.manage` rows added to `permissions.csv` ready for B1 to wire onto the policy engine. Behaviour is the pack's; only the mechanism is interim. |
| F1: build a new tiny AES-GCM helper for secrets | Not needed — these are hashes, not ciphertext. 256-bit CSPRNG secrets are stored as **sha256, no KDF**: there is no dictionary to stretch against, unlike a password. The reasoning is written into `domain/credentials.py` so the next reader does not "fix" it to Argon2. |
| The `mdx_sk_` tag as an auth gate | **No.** The shape check is a length bound. The dev room device authenticates with `dev-room-device-secret` (the pack's "dev configs need no change"), and requiring the tag would also hand an attacker a free oracle: any string without it would skip the hash comparison and answer faster. The tag is for generation and leak-scanning. |

## Two real defects found while building

* **The origin-check middleware blocked every device token request.**
  `OriginCheckMiddleware` covers all state-changing `/auth/*`; a room
  device sends no `Origin` and no `X-Client-Type`, so it was classed as a
  browser and refused **403**. After cut-over, no room in the estate could
  have obtained a token. `/auth/oauth/` is now exempt — CSRF is
  structurally impossible there (a client secret in the body, no ambient
  credential), which is precisely the attack the middleware exists to
  stop. Caught by the e2e test, not by review.
* **`scripts/dev/auth-test.sh` used GNU-only `head -n-1`** and unpadded
  `base64 -d`; both fail on the BSD tools that ship with macOS, where half
  the team runs the dev stack. Found by running it.

## Delivered

1. **Migration `0026_service_credentials`** — `service_credentials` and
   `service_credential_secrets`. Device rows are tenant-scoped and
   readable by `app_role` within the tenant; service rows have a NULL
   tenant so the RLS predicate is never true for them; the secrets table
   has **no `app_role` grant at all**.
2. **`domain/credentials.py`** — secret format, hashing, comparison,
   prefix. **`credential_repository.py`** — create/rotate/revoke/lookup,
   with the hash lookup deliberately keyed on the hash alone and the
   client id checked afterwards. **`credential_service.py`** — the grant,
   the uniform `invalid_client`, rate limit, lock, lifecycle.
3. **`adapters/client_lock.py`** — the fail-closed lock. Two keys, because
   the rule has two clocks: a 10-minute failure counter and a 15-minute
   lock. A fixed-window limiter cannot express that (its window is both
   the counting period and the penalty).
4. **`POST /auth/oauth/token`** — form-encoded, HTTP Basic accepted,
   `Cache-Control: no-store`, RFC 6749 `error` **and** this API's `code`
   in one body, no refresh token ever.
5. **Management routes** — `/admin/credentials[/{id}/rotate|]` and
   `/tenants/{id}/devices[...]`, all mutations behind IDX-A5's step-up.
6. **`scripts/ci/check-identity-grants.py`** + `make check-identity-grants`
   + CI wiring — `app_role` must hold nothing on the six sealed tables and
   read-only on `service_credentials`; also refuses `GRANT ... ON ALL
   TABLES`, which is how such a grant would realistically arrive.
   Verified against a deliberately-introduced violation.
7. **`PIISafeFilter` value patterns** — a new mechanism: the filter was
   key-based, so a secret interpolated into a message (`"configured with
   %s"`) survived. `mdx_sk_…` is now redacted wherever it appears.
8. **Seed** — one dev device in tenant A with the Keycloak secret,
   hash computed in Python rather than hard-coded in SQL. **No service
   credentials**, per the inspect finding.
9. **Tooling** — `scripts/ops/idx-provision-device.py` (replaces seven
   `kcadm` calls), `scripts/dev/auth-test.sh s2s|jwks`.
10. **Docs** — `ambient-device.md` rewritten end to end, `permissions.csv`
    (8 `device.manage` rows), `roles.md`, `error-codes.md` (7 codes),
    `event-kinds.md` (5 kinds).

## Verification

* auth-service unit **292 passed** (19 new), integration **74 passed**
  (26 new: 16 DB, 10 e2e). `libs/observability` 111 passed.
* **Live proof**, not just tests: auth-service started in native mode on
  :8111 against the dev Postgres and Redis, then
  `./scripts/dev/auth-test.sh s2s` green — device got a token, `roles =
  [device]`, `tid = tenant A`, `aud = mdx-api`, no refresh token, wrong
  secret 401. And the token was fed through the real `Claims` model and
  the real `auth.perms` matrix:

  ```
  Claims parsed OK. roles=['device'] tid=…000a
    asr.write        -> ALLOW      audit.read -> deny
    asr.read         -> ALLOW      note.read  -> deny
    dictation.start  -> ALLOW
    tenant.read      -> ALLOW
  ```

  Exactly the documented capture-only grant, and the first time a device
  token has ever passed `Claims`.
* Migration `0026` applies and rolls back cleanly.
* `check-rls` (41 tables), `check-identity-grants`, `lint-imports`,
  `check-metric-names`, `check-audit-insert`, `check-no-os-environ`,
  `check-no-crypto`, ruff: green.
* `docs/api/auth-service-openapi.json` is **unchanged**, and cannot change
  yet: `dump-openapi.py` builds the app in keycloak mode, where the native
  routes are not mounted. Regenerating it is a cut-over-time task, listed
  in the runbook's preconditions. (`make openapi-check` still fails on
  `note-service-openapi.json` — unrelated, pre-existing Ask-feature drift.)

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| Claims-parity green for one device credential | ✅ `test_a_native_device_token_carries_the_same_identity_and_parses`, plus the live check above. **Reinterpreted** — see the finding at the top. |
| Claims-parity for one *service* credential | ⚠️ Not meaningful. No service client has a service-account user, roles or a `tid` in Keycloak, and none is a runtime consumer, so there is no working token to be at parity with. A service credential is exercised instead by `test_a_service_token_is_minted_against_the_platform_tenant`. |
| Every runtime consumer obtains tokens from auth-service with Keycloak stopped | ✅ for the device (the only runtime consumer found). The three service clients are dead — deleted in B2. |
| Secrets never appear in logs | ✅ `test_a_secret_is_redacted_wherever_it_appears_in_a_log` |
| `app_role` selects `service_credential_secrets` → permission denied | ✅ `test_app_role_cannot_read_a_secret_hash`, plus the CI gate |
| Revoking rejects the live token at asr-service within one request | ⚠️ Partly. `test_revoking_pushes_the_credential_onto_the_denylist` proves the push; asserting the rejection *inside asr-service* needs a cross-service harness this repo does not have. The mechanism is the existing sub-denylist (ADR-0040) that already backs user logout. |
| Every production room re-provisioned before B2 | ❌ **Not done** — operator task. |

## Before B2 — the room checklist

Every production room must be re-provisioned and verified before IDX-B2
removes Keycloak. There is no bulk migration and there cannot be:
Keycloak stores client secrets hashed, so they cannot be read out and
carried over. Each room needs a new credential and a config push.

Per room: create → configure → verify (`curl` grant → 200, `roles` and
`tid` correct) → only then delete the Keycloak client. The two coexist
while `MDX_IDP_MODE=keycloak`, so this can run room by room over as long
as it takes. Procedure in `docs/runbooks/ambient-device.md`.

| Room | client_id | Provisioned | Verified | Keycloak client deleted |
| --- | --- | --- | --- | --- |
| _(fill in — never record secrets here)_ | | | | |

I have no access to the production estate, so this table is empty and the
sprint is not complete until it is not.

## Not delivered / next

- `mdx_auth_device_active` gauge — B3's maintenance job samples it (pack K).
- `ClientCredentialsFailureBurst` alert — B3 (pack K).
- `auth.account_purged` / credential purge of long-revoked rows — B3.
- Moving `/tenants/{id}/devices` onto B1's policy engine once it exists;
  the `device.manage` rows are already in `permissions.csv`.
- mTLS / private-key JWT client auth, DPoP, device heartbeat UI: NOT NOW
  (pack).

## Debt / NOT-NOW

- `scripts/dev/keycloak-test.sh` and `auth-test.sh` overlap during the
  cut-over by design; the Keycloak one is deleted in B2.
- The OpenAPI snapshot cannot cover native routes until `dump-openapi.py`
  can build the app in native mode. One-line change, but it belongs with
  the cut-over so the snapshot flips at the same moment the routes do.
- `service` credentials are minted against the platform tenant. If a real
  S2S consumer ever needs a customer workspace, that is a deliberate
  decision to make then — either a tenant-scoped service credential
  (relaxing the 0026 CHECK) or a change to `Claims`.
