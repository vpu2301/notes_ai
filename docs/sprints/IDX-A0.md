# IDX-A0 / FND-0 — Discovery and the dual-issuer decision

**Track:** Foundation · **Window:** W1 · **Date:** 2026-09-06 · **Owner:** CTO
**Outcome:** ADR-0047 (= ADR-IDX-09) merged; `MDX_IDP_MODE` accepts three
values; the inventories below are the input to FND-1 (issuer list), BE-2
(refresh routing) and BE-3 (email code).

## Where the decision lives

The IDX pack's `01-ARCHITECTURE-DECISIONS.md` is outside this repository
and was not present when this sprint ran. ADR-IDX-09 is therefore recorded
in-repo as **[ADR-0047 — A bounded dual-issuer period](../adr/0047-dual-issuer-period.md)**,
in the repo's own decision-memo format, and that file is the copy the code
references. Fold it back into the pack when the two are next reconciled
(BE-4 item 4).

Cut-over plan §C3 is replaced there: no big-bang window in this batch.

## Reconciling with what has already shipped

The batch brief assumed IDX-A0/A1 had not been run. **Most of A1 through
A5 has in fact landed** on branch `S01`, gated behind `MDX_IDP_MODE`. What
that changes for this batch:

| Batch item | State found | Action |
| --- | --- | --- |
| A1 identity tables | **Done** — migrations `0024`–`0030`: `identities`, `auth_challenges`, `auth_sessions`, `identity_totp`, `identity_recovery_codes`, `service_credential*`, `tenants.kind`, backfill, `profile_of_subs`, RLS, session rotation | BE-1 is reduced to its *deltas* (`legacy_idp`, the bridge assertion) |
| `identities.mfa_enabled` | **Already exists** (`0024_idx_identities.sql:74`), backfilled from `users.mfa_enrolled_at` in `0027` | verify only |
| `check-identity-grants.py` | **Already in CI** (`.github/workflows/ci.yml`, `make check-identity-grants`) | A0 §C4 satisfied on day one |
| A2 issuer/JWKS/TokenService/SessionService | **Done**, native-only | BE-2 adds `dual` routing, not the issuer |
| A3 email-code signup | **Done**, native-only (`routers/email_code.py`) | BE-3 adds the `dual` rules and the first-use test |
| A4 native password login | **Not run** — `/auth/login` and `/auth/password/*` are Keycloak-only | the reason a big-bang cut-over is not available; see ADR-0047 |
| A5 account/MFA/sessions | **Done**, native-only | `dual` gets `account.router` (for `PATCH /auth/me`) but not `mfa_native` |

The Foundation pack's S0 work (`libs/models`, `libs/jobs`) does not touch
the issuer path; no Keycloak-only assumptions to fold in beyond the Helm
values and contract tests already covered by FND-1.

## Inventory 1 — issuer configuration, per service

Every service reads the same four names, with identical defaults. FND-1
adds a fifth, `AUTH_ISSUERS_JSON`, which supersedes the first three when
set.

| Service | config module | `AUTH_ISSUER` | `AUTH_JWKS_URL` | `AUTH_AUDIENCE` | `AUTH_ISSUERS_JSON` (FND-1) |
| --- | --- | :-: | :-: | :-: | :-: |
| auth-service | `auth_service/config.py` | ✓ | ✓ | ✓ | ✓ (mode-derived, see below) |
| note-service | `note_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| asr-service | `asr_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| autocomplete-service | `autocomplete_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| notification-service | `notification_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| dictation-service | `dictation_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| nlp-service | `nlp_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| generation-service | `generation_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| `_template` | `template_service/config.py` | ✓ | ✓ | ✓ | ✓ |
| **asr-worker** | — | — | — | — | **n/a: verifies no tokens.** It consumes jobs from the queue; there is no HTTP surface and no `verify_token` call. FND-1 §4's contract test does not apply. |

Defaults, unchanged: `AUTH_ISSUER=http://localhost:8088/realms/notes`,
`AUTH_JWKS_URL=…/protocol/openid-connect/certs`, `AUTH_AUDIENCE=mdx-api`,
`AUTH_CLOCK_SKEW_SECONDS=30`.

**auth-service is the exception.** Its trusted list is derived from its
mode (`main_deps.auth_issuers`), because it is the service that decides
which issuers exist: `keycloak` → the configured list; `dual` → that list
plus its own `AUTH_ISSUER_URL`; `native` → its own issuer *only*.

### Where the values come from

| Environment | File | Mechanism |
| --- | --- | --- |
| dev / CI | `docker-compose.override.yml` | the `x-auth-env` YAML anchor, merged into all 8 HTTP services (lines 162, 255, 344, 425, 448, 493, 540, 591) |
| staging / prod | `infra/k8s/notes/values.yaml` → `commonEnv` | `templates/apps.yaml:87` ranges over `commonEnv` into every Deployment |
| local shell | `.env.example` | documented, commented out by default |

All three now carry `AUTH_ISSUERS_JSON` with **both** issuers.

### Verification-call sites (what FND-1 had to change)

Not only the FastAPI dependency. `scripts/ci/check-auth-issuer-config.py`
exists to keep this list from growing back:

| Site | Why it is separate from `current_user` |
| --- | --- |
| `dictation_service/ws/upgrade.py` | WebSocket upgrade — no `Depends` chain |
| `dictation_service/ws/handler.py` | in-band `RefreshToken` frame on a live socket |
| `notification_service/ws/upgrade.py` | WebSocket upgrade |
| `auth_service/routers/login.py` ×2 | verifies a token Keycloak just minted; verifies the bearer accompanying a logout |
| `auth_service/routers/session_native.py` | verifies the bearer accompanying a native logout, to denylist its `sid` |

A socket that trusted a different issuer set than the REST surface would
be an outage confined to one endpoint — the hardest kind to find.

## Inventory 2 — who reads the refresh cookie (input to BE-2 routing)

Cookie name `mdx_rt` (`AUTH_COOKIE_NAME`), path `/auth`, HttpOnly,
`SameSite` from `AUTH_COOKIE_SAMESITE` (default lax), `Secure` from
`AUTH_COOKIE_SECURE`.

| Reader | File | Note |
| --- | --- | --- |
| Keycloak session router | `auth_service/routers/login.py` — `_presented_token`, `_set_refresh_cookie`, `_clear_refresh_cookie` | `/auth/login`, `/auth/refresh`, `/auth/logout` |
| Native session router | `auth_service/routers/session_native.py` — same three helpers | `/auth/refresh`, `/auth/logout`, `/auth/token`; **mounted instead of login's in native mode** |
| Transport policy | `auth_service/domain/transport.py` | decides cookie (web) vs body (native app) from `X-Client-Type` |
| Origin check | `auth_service/middleware/origin_check.py` | the CSRF control that exists because the cookie is ambient; native mode only |
| Web SPA | `web/src/api/auth.ts`, `web/src/api/types.ts` | never touches the value — it is HttpOnly; the SPA only knows refresh is cookie-borne |
| macOS app | `macos/Sources/NotesAICapture/SessionStore.swift:155` | names the cookie to *delete* it on sign-out |
| iOS app | `ios/Sources/NotesAICapture/SessionStore.swift:487` | same |

**Consequence for BE-2.** Both routers claim `/auth/refresh` and
`/auth/logout`, so `dual` cannot mount both as-is. The routing rule is
therefore *inside* the native handler, keyed on the token's shape
(`nrt_` prefix), and the cookie name does not change — no client of any
kind needs a release for the dual period.

## Inventory 3 — the challenge/code/email machinery BE-3 reuses

| Concern | Module | Reused as |
| --- | --- | --- |
| Code generation, hashing, expiry, attempts | `domain/email_code.py` (243 ln) | `EmailCodeService`'s core; `code_hash = sha256("<code>:<row id>")`, bound to the row so a hash from a backup cannot be replayed |
| Orchestration, rate limits, lockout | `domain/email_code_service.py` (710 ln) | extended, not rewritten |
| Store | `auth_challenges(kind='email_login')`, migration `0024` | unchanged; `kind` CHECK already allows `email_login`, `mfa_totp`, `invite` |
| Provider abstraction | `adapters/email.py` (239 ln) — `EmailProvider`, `SmtpProvider` (aiosmtplib), `MockProvider`, `EmailDeliveryError`, `EmailPermanentError` | unchanged; FND-2 needs **no code change**, only credentials |
| Templates / copy | `domain/compose.py` (342 ln), `domain/copy.py` (817 ln) | en/de/uk; `compose.format_code` renders `482 913` |
| Send + retry | `domain/mailing.py`, `delivery/worker.py` | unchanged |
| Security notices | `domain/security_mail.py` | unchanged |

## Inventory 4 — mail environment names (input to FND-2)

The brief guessed `MDX_SMTP_*`. The repository uses **two prefixes**, and
FND-2 must set the auth-service one:

| Purpose | auth-service | notification-service |
| --- | --- | --- |
| provider selector | `MDX_EMAIL_PROVIDER` (`mock` \| `smtp`) | `MDX_EMAIL_PROVIDER` |
| host / port | `MDX_AUTH_SMTP_HOST` / `MDX_AUTH_SMTP_PORT` | `MDX_SMTP_HOST` / `MDX_SMTP_PORT` |
| TLS | `MDX_AUTH_SMTP_USE_TLS` | `MDX_SMTP_USE_TLS` |
| credentials | `MDX_AUTH_SMTP_USERNAME` / `MDX_AUTH_SMTP_PASSWORD` | `MDX_SMTP_USERNAME` / `MDX_SMTP_PASSWORD` |
| from | `MDX_AUTH_EMAIL_FROM`, `MDX_AUTH_EMAIL_FROM_NAME`, `MDX_AUTH_EMAIL_REPLY_TO` | `MDX_EMAIL_FROM`, `MDX_EMAIL_FROM_NAME` |
| public app origin | `MDX_APP_BASE_URL` | — |
| cookie | `AUTH_COOKIE_SECURE`, `CORS_ALLOWED_ORIGINS` | `CORS_ALLOWED_ORIGINS` |

Current defaults are `sales@notes-ai.local` / `"Notes AI"` — the product
name in this repository is **Notes AI**, not the brief's "Notes AI".

## Inventory 5 — how tests and load tests obtain tokens

| Consumer | Mechanism | Affected by `dual`? |
| --- | --- | --- |
| `docs/testing/README.md:164`, `:386` | `POST /auth/login` then `/auth/me` | **No** — `/auth/login` is unchanged in `dual` |
| `scripts/loadtest/auth-k6.js`, `run-auth-loadtest.sh` | `/auth/login` | **No** |
| `scripts/loadtest/autocomplete-k6.js` | `/auth/login` for a bearer | **No** |
| `scripts/smoke/notes_e2e.py`, `scripts/dev/mdx-test.sh` | `/auth/login` | **No** |
| service unit/integration suites | `auth.testing` / `auth.pytest_plugin` — RS256 tokens minted in process | **No** — and FND-1 extends it with a two-issuer fixture |

Nothing in the test estate needs a change for the dual period. That is
the point of leaving `/auth/login` alone.

## Acceptance

- [x] ADR-0047 (ADR-IDX-09) merged; options A/B/C, evidence, risks, the
      revert trigger, and the `POST /auth/token` → `409 legacy_session`
      consequence all recorded.
- [x] `MDX_IDP_MODE` accepts `keycloak` \| `dual` \| `native`, defaults to
      `keycloak` (`auth_service/config.py`), and is logged at startup
      alongside the resolved issuer list (`main.py`, `auth-service starting`).
- [x] Inventory tables above: issuer env names per service, refresh-cookie
      readers, mail env names, token acquisition in tests.
- [x] `check-identity-grants.py` in the CI gate (was already there);
      `check-auth-issuer-config.py` added beside it by FND-1.
