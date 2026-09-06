# IDX-A2 — Token issuer, sessions, refresh & workspace-scoped tokens

**Status:** partially delivered (2026-09-05) — blocked on IDX-A1 for the session half.
**Branch:** S01 (uncommitted working tree).

## Inspect-first findings

| Item | Finding |
| --- | --- |
| `libs/auth` `Claims` | `extra="forbid"`, frozen. Required: `sub: UUID`, `tid: UUID`, `roles: list[str]`, `sid: str`, `iss`, `aud: str \| list[str]`, `exp`, `iat`. Defaults: `scope=""`, `mfa=False`, `mfa_enrolled=False`, `nbf`. Optional/ignored: `jti, typ, azp, auth_time, acr, session_state, allowed-origins, preferred_username, name, given_name, family_name, email, email_verified, realm_access, resource_access`. No `email`/`name` **required**. |
| JWKS cache (`auth/jwks.py`) | TTL 300 s; refresh on kid miss with a 5 s per-issuer rate limit; per-issuer lock (one fetch per storm); unknown issuer rejected before HTTP; fetch failure → `JwksFetchError`, cached keys keep serving until TTL. |
| Verifier | RS256 only (alg pinned before decode), `kid` mandatory, `aud`/`iss`/`exp`/`nbf` verified, `iat` tolerated, 30 s leeway. |
| Config names in every service | `AUTH_ISSUER`, `AUTH_JWKS_URL`, `AUTH_AUDIENCE` (default `mdx-api`), `AUTH_CLOCK_SKEW_SECONDS` — identical across the 9 services. Cut-over = set `AUTH_ISSUER=<AUTH_ISSUER_URL>` and `AUTH_JWKS_URL=<AUTH_ISSUER_URL>/.well-known/jwks.json`. |
| `current_user` wiring | note/asr/nlp/dictation build `build_current_user(...)` lazily from `state.jwks_cache` + settings; notification-service builds `state.current_user_dep` once in `build_state`. Contract test mirrors both. |
| `routers/login.py` | `_set_refresh_cookie(response, token, max_age)`, `_clear_refresh_cookie(response)`, `_audit_login(state, access_token, kind, severity)`; metrics `mdx_auth_login_total{result}`, `mdx_auth_refresh_replay_total{tenant_id}`, `mdx_auth_logout_total`; replay code `auth_refresh_replay` via `problem_extras`; refresh reads the cookie only; logout is idempotent and denylists the bearer's `sid`. Cookie: `SameSite` from `AUTH_COOKIE_SAMESITE` (default lax), `Secure` from `AUTH_COOKIE_SECURE`, path `/auth`. |
| `revocation.py` | `RedisSessionDenylist.revoke_sid(sid, ttl_seconds)`, `revoke_sub(sub, ttl_seconds)`, `clear_sub`; keys `mdx:revoked:sid:*` / `mdx:revoked:sub:*`; TTL floor 30 s; fail-open reads. Existing `MDX_REVOKED_SUB_TTL_SECONDS` (1200) — now also accepted as `AUTH_REVOKED_SUB_TTL_SECONDS`. |
| `/auth/me` | joins `users` (PK `sub`, per-tenant) + open `mfa_reminders` under `tenant_connection(app_pool, claims.tid)`; returns `{claims, db_user}`. |
| Data model | `users` (per-tenant principal), `tenant_memberships(tenant_id, user_sub, role ∈ owner/admin/member/assistant/viewer, status ∈ active/invited/suspended)`, `tenant_of_sub`, `active_tenant_ids`. **No `identities`, no `auth_sessions`** — IDX-A0/A1 have not been run (no `docs/sprints/`, no ADR-IDX-*, no `MDX_IDP_MODE`). |
| Pools | `ServiceState` already has `tenant_writer_pool` (SessionService's home). |

## Delivered (A1-independent)

1. **Signing keys** — `domain/signing_keys.py`: `AUTH_SIGNING_KEYS_JSON` list `{kid, private_pem, not_after}`; active = furthest `not_after` still ahead; JWKS publishes while `not_after + AUTH_ACCESS_TTL_SECONDS` is ahead; kid must equal `sha256(SPKI)[:12]`; RSA ≥ 2048. Dev fallback `AUTH_SIGNING_KEYS_FILE`, refused when `ENVIRONMENT=production`.
2. **`TokenService.mint`** — `domain/token_service.py`: exact `Claims` shape (`iss, aud, sub, sid, tid, roles, scope, mfa, mfa_enrolled, iat, exp, jti, typ=Bearer, azp=aud`, optional `email`, `name`). Takes plain values, not A1 rows.
3. **Discovery + JWKS** — `routers/wellknown.py`: `/.well-known/openid-configuration`, `/.well-known/jwks.json` (`Cache-Control: public, max-age=300`, metric `mdx_auth_jwks_requests_total`, asserts no private members). Mounted only when `MDX_IDP_MODE=native`.
4. **Origin check** — `middleware/origin_check.py` (F5): web/absent client type must present an allowed `Origin`/`Referer` on state-changing `/auth/*`; native exempt only with header **and** no Origin. 403 `origin_not_allowed`. Mounted in native mode only (see Debt).
5. **Transport** — `domain/transport.py`: `X-Client-Type` parsing, `TokenResponse` superset of `LoginResponse`, web omits `refresh_token`, native carries it.
6. **Mode switch** — `MDX_IDP_MODE=keycloak|native` in config; `build_issuer()` in `main_deps` (native mode without keys = startup failure); `ServiceState.signing_keys/token_service`.
7. **Key tooling** — `scripts/ops/gen-signing-key.py` (RSA-3072, kid derivation, rotation notes); dev key `infra/dev/auth-signing-dev.json` (kid `8b5e3d8e2576`, not_after 2030-01-01) mounted by compose as `/etc/mdx/auth-signing.json`; `scripts/ci/check-dev-keys.py` + `make check-dev-keys` + CI step; gitleaks allow-list entry for the dev file.
8. **Contract harness** — `libs/auth/src/auth/testing.py` (`TestIssuer`: in-memory RSA key, JWKS over `MockTransport`, `mint`/`mint_raw`); `tests/contract/test_token_contract.py` parametrised over note/asr/nlp/dictation/notification `deps.current_user`: accepts an auth-service token, rejects wrong `aud`, wrong `iss`, expired. Zero changes to `libs/auth` verification code.
9. **Docs** — `docs/api/error-codes.md` (new, all A2 codes), audit kind `auth.tenant_switched` in `audit_kinds.py` + catalogue, `.env.example`, `infra/dev/README.md`.

Verification: auth-service unit 170 passed (37 new); libs/auth 67 passed; contract 15 passed; mypy --strict clean on new modules; `check-no-os-environ`, `check-dev-keys`, `check-metric-names`, `lint-imports` (21 contracts) green; OpenAPI snapshot unchanged in keycloak mode; native issuer booted inside the rebuilt compose image via the mounted dev key (one-off `docker compose run`).

## Not delivered — blocked on IDX-A1

- `SessionService` (start/refresh/switch_tenant/revoke/revoke_all) — needs `identities`, `auth_sessions`, membership→role mapping (ADR-IDX-07), platform tenant.
- `routers/session_native.py`: native `/auth/refresh`, `/auth/logout`, `/auth/token`, `/auth/me` extension; denylist push wiring for those paths; `mdx_auth_token_switch_total`, `mdx_auth_denylist_push_failed_total`, `mdx_auth_session_active`.
- Renaming `routers/login.py` → `login_keycloak.py` (deferred until `session_native.py` exists; the Keycloak router serves both modes today).
- Tests L: refresh happy path/grace/replay/expiry, `/auth/token` membership matrix, DB-backed `sid` check, tenant-isolation matrix for sessions.

## Debt / NOT-NOW

- **Origin check vs. current native apps**: today's macOS/iOS clients and the smoke scripts send neither `X-Client-Type` nor `Origin`. The middleware is therefore native-mode only; the A5 cut-over needs M1/I1's header (or a temporary allow) first. Record as a cut-over precondition in the A0 runbook.
- Root venv lacks `pytest-asyncio`; async suites need `uv run --with pytest-asyncio` locally (CI installs dev deps).
- `check-no-os-environ` scans `git ls-files` only — untracked new files are not scanned until added.
- Checked-in dev private key is a deliberate exception to the repo's "never commit a key" rule (pack F1); guarded by `check-dev-keys` + gitleaks allow-list.
