# IDX-A3 — Email one-time-code signup & login, rate limiting, lockout

**Status:** delivered (2026-09-05). A brand-new address signs up, receives a
code, and gets a workspace-scoped token, end to end against the dev stack.
**Branch:** S01 (uncommitted working tree).

## The one deviation from the pack, stated up front

A3's route layer needs `identities`, `auth_challenges`, `tenants.kind` and a
platform tenant — all of which the pack assigns to **IDX-A1**, which has not
been run — plus `SessionService.start`, which IDX-A2 left undelivered for the
same reason. Reporting "still blocked" a second time would have delivered
nothing, so this sprint carries the **minimum A1 slice A3 consumes** and the
**one A2 method** it calls:

* migration `0024_idx_identities` — `tenants.kind`, `identities`,
  `auth_challenges`, `auth_sessions`, the platform tenant row;
* `domain/session_service.py::SessionService.start` only. `refresh`,
  `switch_tenant`, `revoke` and `routers/session_native.py` remain A2's,
  untouched — there is no route to exercise them and inventing their
  replay-detection semantics here would be guessing at A2's contract.

Nothing here forecloses A1 proper: it extends these tables (external IdPs,
per-identity settings, deletion tombstones) rather than replacing them.

One addition the pack's F3 transaction does not list: the signup transaction
also writes the `users` row. `users` is how the rest of the estate resolves a
`sub` to a person — note-service reads it for share recipients,
notification-service for an address to mail. An identity without one holds a
valid token and is invisible to both, so it is written in the same
transaction as the identity, tenant and membership.

## Inspect-first findings

| Item | Finding |
| --- | --- |
| Email adapter | `adapters/email.py`: `EmailProvider` ABC (`send(OutboundEmail) -> SendResult`, `aclose`), `SmtpProvider`, `MockProvider` (captures in `.sent`, refuses production), `build_provider(kind=smtp\|mock, …)`. Transient `EmailDeliveryError` vs `EmailPermanentError`. |
| Templates | `adapters/templates.py`: Jinja `FileSystemLoader`, `StrictUndefined`, `KINDS` gate; text bodies in `domain/copy.py::_TEXT`, subjects in `SUBJECTS`, per-kind variable builders in `domain/compose.py`. Languages en/de/uk. |
| Rate limiters | Two hand-rolled fixed-window INCR+EXPIRE limiters (`nlp_service.deps.rate_limited`, `auth_service.rate_limit.PasswordResetRateLimiter`). Extracted to `libs/ratelimit`; migrating the two existing callers is debt. |
| IP resolution | Three ad-hoc XFF readers, all trusting the first hop. `ratelimit.client_ip` implements the trusted-proxy rule instead and is used by the new routes. |
| `tenants` | No `kind` column (added by 0024). `tenants.name` is UNIQUE — every `ada@` on every domain wants the workspace name "ada", hence the collision retry. |
| `users` | RLS-scoped **even for `tenant_writer`** (`users_writer_tenant` reads `app.tenant_id`), unlike `tenants`/`tenant_memberships` which are `USING (true)`. The signup transaction therefore sets `app.tenant_id` with `set_config(..., true)` after the tenant row exists. |
| Membership → JWT roles | No mapping existed (ADR-IDX-07 is not in the repo). Added explicitly in `identity_repository._PLATFORM_ROLES`: owner/admin → `tenant_admin`, member/assistant → `member`, viewer → `viewer`, unknown → `viewer`. |
| `no_workspace` | Already contracted at **409** in `docs/api/error-codes.md` (an A2 entry). Verify uses 409, not a second status for the same code. |
| `EmailStr` | `email-validator` rejects the reserved `.test` TLD. Integration fixtures use `.example`. |

## Delivered

1. **`libs/ratelimit`** — `FixedWindowLimiter.allow(scope, subject, limit, window_seconds, fail_open, cost) -> Decision`; `RateLimiterUnavailableError` when fail-closed and Redis is down; refused calls still count. `client_ip` + `parse_cidrs`: first untrusted hop from the right, only when the peer is a trusted proxy. 15 unit tests.
2. **Mail** — kinds `auth_code` / `auth_locked` (subjects, text bodies, six HTML templates, en/de/uk). No links, no echo of the address, code never in the subject.
3. **Email-code core** — `domain/email_code.py`: code generation, challenge-bound hash, constant-time compare, the pure verify state machine, `LockoutPolicy`, `personal_workspace_names`, and the `ChallengeStore` Protocol.
4. **Migration `0024_idx_identities`** — `tenants.kind` (`personal|team|platform`, defaulting existing rows to `team`), the platform tenant `…0000f1`, and `identities` / `auth_challenges` / `auth_sessions`. These three have no `tenant_id` to scope by, so their isolation is the role grant plus a `tenant_writer`-only RLS policy; `app_role` is granted nothing and has no policy.
5. **`domain/identity_repository.py`** — `PgChallengeStore` (conditional-UPDATE `consume`, supersede-on-start, `latest_open_for_email`), `IdentityRepository` (lookup, the four-row signup transaction with name-collision retry ×3, reactivate, `note_successful_login`, `register_failure` under `FOR UPDATE`, `claim_lock_notice`), `SessionRepository`, and the membership→roles map.
6. **`domain/session_service.py`** — `SessionService.start`: a new `sid` per verify, refresh token generated once and stored only as sha256, roles from the membership.
7. **`domain/email_code_service.py`** — the sequence: limits → lookup → cooldown → supersede → challenge → mail → uniform 202; and verify → state machine → consume → resolve-or-signup → session. `CodeMailer` sends inline under `AUTH_EMAIL_SEND_TIMEOUT_SECONDS`. Metrics `mdx_auth_otp_start_total`, `mdx_auth_otp_verify_total`, `mdx_auth_signup_total`, `mdx_auth_email_send_seconds`, `mdx_auth_email_send_failed_total`.
8. **`routers/email_code.py`** — `POST /auth/email/start|verify`, `AuthResult`, the refresh cookie for web / body token for native, audit (`auth.otp_requested` and `auth.otp_failed` on the platform tenant; `auth.signup`, `auth.login{method:"email_code"}`, `auth.account_deletion_cancelled` on the user's own tenant; `auth.account_locked` sec on the platform tenant). Mounted **only** in `MDX_IDP_MODE=native`.
9. **Wiring** — `build_email_code_service` in `main_deps`; native mode also brings up the mail provider and the Redis client. Missing signing key or mail provider ⇒ the service is not built and the routes 404 rather than half-work.
10. **Docs/config** — `AUTH_REFRESH_TTL_SECONDS`, `AUTH_PLATFORM_TENANT_ID`, `AUTH_EMAIL_SEND_TIMEOUT_SECONDS` in `.env.example`; `error-codes.md` extended (including what `/start` deliberately does *not* return).

### Decisions the pack left open

| Question | Answer, and why |
| --- | --- |
| Challenge id: server- or DB-assigned? | Drawn by the service before the INSERT. The stored hash is bound to the id (F1); letting Postgres assign it would mean a row briefly live with a placeholder hash, which a concurrent start could supersede or a verify could hit. |
| `otp_cooldown` subject | The pack keys it on `challenge_id`, but with no separate resend endpoint the only way to ask again is another `start`, which has no id yet. Subject is the hashed address; the authority is `auth_challenges.created_at` (Redis is the fail-open first check). |
| Unknown `challenge_id` on verify | `challenge_expired`, not a distinct code. It is indistinguishable from a challenge that expired and was purged, and the client's next step is the same. |
| Locked account on `/start` | Still creates a challenge row, so the 202 points at something real; the code is simply never mailed, so it cannot be verified. The lock holds without the response admitting it. |
| Correct code from a locked account | Allowed, and clears the lock. The code proves possession of the mailbox, and the pack's "successful login resets counters" says so. |
| `lock_count` on success | **Not** reset — it is what makes the next lock longer than the last. `failed_login_count` and `locked_until` are. |

## Verification

* auth-service unit: **224 passed** (25 new in `test_email_code_routes.py`).
* `libs/ratelimit`: 15 passed.
* Integration against the dev Postgres (`RUN_DB_INTEGRATION=1`): **15 passed** —
  `test_email_code_db.py` (11: signup atomicity and all four rows, workspace
  name collision, duplicate address, concurrent `consume` → one winner,
  supersession, lockout under 10 concurrent failures, one lock notice out of
  five racing claims, refresh-token hashing, `app_role` denied on all three
  tables, a new workspace invisible from tenant A's scope, the platform
  tenant) and `test_email_code_e2e.py` (4: the real app in native mode with
  real pools and real Redis — signup → workspace → RS256 token, second
  sign-in reuses the workspace with a fresh `sid`, known/unknown `/start`
  indistinguishable, `attempts_left`).
* Migration `0024` applies and rolls back cleanly (`make migrate-up` /
  `migrate-down` / `migrate-up`).
* Audit rows confirmed in `audit.events`: `auth.signup` and `auth.login` are
  seq 1 and 2 **on the new personal tenant**; `auth.otp_requested` /
  `auth.otp_failed` on the platform tenant, carrying neither address nor code.
* `mypy --strict` on the four new modules: clean apart from the repo-wide
  `import-untyped` noise for `audit`/`auth`/`db`/`asyncpg`/`ratelimit` (no
  `py.typed` anywhere in `libs/`; identical on existing modules).
* `check-rls` (34 tables, RLS+FORCE), `lint-imports` (21 contracts),
  `check-audit-insert`, `check-metric-names` (121 instruments),
  `check-no-os-environ`: green.
* auth-service OpenAPI snapshot unchanged — the routes are native-only and the
  dump runs in keycloak mode. (`make openapi-check` fails on
  `note-service-openapi.json`; that drift is the unrelated, pre-existing Ask
  feature and was already `M` before this sprint.)

## Acceptance criteria

| Criterion | Where it is proven |
| --- | --- |
| New email completes signup; `count(*) FROM tenants WHERE kind='personal'` +1 | `test_a_brand_new_address_signs_up_and_gets_a_workspace_token` (e2e, real DB) |
| `/start` byte-identical for known and unknown | `test_start_is_identical_for_known_and_unknown_addresses`, `test_start_looks_the_same_for_a_known_and_an_unknown_address` |
| The sixth wrong code is impossible | `test_the_fifth_wrong_code_consumes_the_challenge` |
| Redis down ⇒ `/start` 503 and no mail; `/verify` still works | `test_start_fails_closed_when_redis_is_down_and_verify_still_works` |
| No log line carries an address or a code | `test_no_log_record_carries_an_address_or_a_code` (plus the audit-payload twin) |
| Keycloak-mode suite green | 224 unit tests; `test_the_routes_do_not_exist_in_keycloak_mode` |

## Not delivered / next

- The rest of IDX-A2's session surface: `refresh`, `logout`, `/auth/token`,
  the `/auth/me` extension, denylist push on those paths, and renaming
  `routers/login.py` → `login_keycloak.py`. A3 opens sessions; nothing yet
  rotates or ends them, so a native deployment's users stay signed in for
  `AUTH_REFRESH_TTL_SECONDS` and log out only by discarding the token.
- MFA branch on verify (A5). `identities.mfa_enabled` exists and is always
  false; verify returns `authenticated` unconditionally, per the pack's stub
  instruction. The `AuthResult.mfa_required` shape is already in `transport`.
- Password login and the 423 `account_locked` response (A4). The lockout
  columns and arithmetic this sprint added are what A4 increments.

## Debt / NOT-NOW

- Migrate `PasswordResetRateLimiter` and `nlp_service.deps.rate_limited` onto
  `libs/ratelimit` (the pack's stated reason for extracting it).
- Replace the three first-hop XFF readers with `ratelimit.client_ip`.
- `auth_challenges` purge 24 h after expiry: B3. Rows accumulate harmlessly
  until then; the `auth_challenges_expiry_idx` for that sweep already exists.
- Reaching a lockout purely through exhausted codes takes over half an hour
  (five codes per address per quarter hour × ten challenges). That is the
  intended cost, but it means the OTP path alone is a slow way to lock an
  account; A4's password failures are the fast one.
- `check-no-os-environ` scans `git ls-files` only — the new files are not
  scanned until they are added.
- CAPTCHA: NOT NOW (pack).
