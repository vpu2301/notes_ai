# IDX-W1 — Web: authentication flows

**Status:** client half delivered (2026-09-05). Two of the sprint's routes have
no server to talk to and were **not** built; a third was built against the
contract the server actually serves rather than the one the pack describes.
**Branch:** S01 (uncommitted working tree).

## The finding that reshapes this sprint

The pack's dependency line reads *"Depends on: A5 (all auth endpoints live,
issuer cut over), B1 (invitations)"*. Neither holds, and the gap is not a
detail of sequencing — it decides what a browser can do.

`SessionService` (`domain/session_service.py`) has exactly one method,
`start`. Its own docstring says so: *"the IDX-A2 slice IDX-A3 needs"*.
`refresh`, `switch_tenant` and `revoke` were never written, and neither was
`routers/session_native.py`. `routers/login.py` — which serves `/auth/login`,
`/auth/refresh` and `/auth/logout` — is mounted in **both** modes and calls
Keycloak unconditionally (`state.keycloak.password_grant`, `.refresh`).

The consequence, in native mode:

1. `POST /auth/email/verify` mints a **native** session and puts a **native**
   refresh token in the `mdx_rt` cookie.
2. The SPA's next `POST /auth/refresh` — at boot, and a minute before every
   expiry — hands that native token to **Keycloak**, which has never heard
   of it.
3. The refresh fails, `onAuthLost` fires, the person is signed out.

So an email-code sign-in survives exactly one access-token lifetime and does
not survive a page reload. **Every flow in this sprint is subject to that
ceiling**, and no amount of client work lifts it: the fix is A2's remaining
half, in the auth service. It is recorded as the first item under "Not met".

In keycloak mode the mirror image applies — `email_code`, `mfa_native`,
`account`, `oauth` and `credentials` are mounted only under
`MDX_IDP_MODE=native` (`main.py:230-256`), so the email-code and step-up
routes answer 404. `.env.example`, `docker-compose.override.yml` and the
Helm values all still say `keycloak`.

## Inspect first

### Web (§B)

| Item | Finding |
| --- | --- |
| `api/http.ts` | `BASES` (`VITE_AUTH_BASE` → :8000, asr :8001, notification :8004, note :8006); `api<T>(base, path, {method, json, form, query, auth, credentials, signal})`; `ApiError.status/.problem/.code/.detail/.isConflict`; `parseProblem` handles RFC 9457, FastAPI `{detail: "…"}` and `{detail: [{msg}]}`; module-level `accessToken`; single-flight `refreshSession()`; one silent-refresh retry on 401 when `auth !== false`; `setSessionListener({onRefreshed, onAuthLost})`. Kept whole. |
| `rawRequest` | Builds the `Authorization` header **twice** — once into `headers`, then again in the `doFetch` spread. Harmless (same value) but it is the line W1 edits, so it is now built once. |
| `api/auth.ts` | `login(email, password, otp?)`, `logout()`, `fetchMe()`. Kept; extended. |
| `api/types.ts` | `LoginResponse {access_token, expires_in, token_type?}`, `MeResponse {claims, db_user}`. Header claims the DTOs are verified against `docs/api/*-openapi.json` — see the snapshot finding below. |
| `auth/AuthContext.tsx` | `status: restoring \| authenticated \| anonymous`; `scheduleRefresh` at `expires_in - 60` s (floor 10 s); boot = `refreshSession()` → `fetchMe()`; `login(email, password, otp)`; `logout` also calls `preventSilentSignIn()`. |
| `pages/LoginPage.tsx` | `login-shell dotted` / `login-card`; branches on `otp_required` / `otp_invalid`; `offerToSavePassword` (Credential Management API) is fired and deliberately not awaited. |
| `App.tsx` | `BrowserRouter`; `RequireAuth` renders a `splash dotted` while restoring and `<Navigate to="/login" state={{from}}>` when anonymous; `/s/:token` is the one public route. |
| `shell/AppShell.tsx › AccountMenu` | Reads `me?.db_user?.email` at line 188 and `displayName` from the context, which itself reads `me.db_user`. Both moved behind `identity`. |
| Styles / components | `login-*` in `pages.css`; `modal-overlay/modal/modal-h/modal-b/modal-f` in `components.css`; `banner banner-danger`, `btn primary\|ghost\|danger lg block`; `useDismiss`, `ConfirmDialog`, `useToast({toast,success,error,info})`. No component library, no i18n, no analytics. |
| Test infra | **None.** No Vitest, no Playwright, no `tests/` under `web/`. `package.json` scripts are `dev`/`build`/`preview`/`typecheck` only. |

### Server — what §G's endpoints actually are

| §G says | Reality |
| --- | --- |
| `POST /auth/email/start` | ✅ `routers/email_code.py`, native only. 202 `{challenge_id, expires_in, resend_after}`; body takes an optional `lang`. |
| `POST /auth/email/verify` | ✅ same router. Returns `AuthResult`. |
| `POST /auth/login` | ✅ `routers/login.py`, **Keycloak-backed in both modes**. Returns the old `LoginResponse`, not `AuthResult`. |
| `POST /auth/mfa/verify` | ✅ `routers/mfa_native.py` (native) — `{challenge_id, method, code}`, `method ∈ totp \| recovery_code`. |
| `POST /auth/password/forgot` | ✅ `routers/password.py`, **keycloak mode only**. |
| `POST /auth/password/reset` | ✅ same — but the body is **`{token, new_password}`**, not `{challenge_id, code, new_password}`. |
| `POST /auth/refresh`, `/auth/logout` | ✅ Keycloak-backed in both modes (see above). |
| `POST /auth/token` | ❌ **Does not exist.** The only `/token` in the service is `POST /auth/oauth/token` (B1b `client_credentials`, for devices and services). |
| `GET /auth/me` | ✅ — but **not extended**. `routers/me.py` still selects from `users` and returns `{claims, db_user}`. No `identity`, no `memberships`. |
| `PATCH /auth/me` | ✅ `routers/account.py`, native only. `{display_name?, locale?, timezone?}` → `IdentitySummary`. |
| `POST /auth/reauth` | ✅ — 204, body `{method ∈ totp \| recovery_code \| email_code, code, challenge_id?}`. |
| `POST /auth/reauth/email/start` | ❌ The route is **`POST /auth/reauth/start`**, takes no body, requires a bearer, and the **server** decides the methods: MFA users get `[totp, recovery_code]` and no challenge; everyone else gets `[email_code]` with a `challenge_id` and a mailed code. |
| `GET /invitations/:token`, `POST …/accept` | ❌ **Nothing.** `grep -rn invitation services libs infra/postgres web/src` returns one hit, an unrelated comment in `ComingUp.tsx`. B1 was never run. |

### Four more contract corrections

1. **`AuthResult` discriminates on `status`, not `kind`.** `domain/transport.py`:
   `status: "authenticated" | "mfa_required"`, and the token fields carry
   defaults precisely so an `mfa_required` result can be a real 200 with an
   empty `access_token`. `identity` and `memberships` are top-level and
   nullable; there is also `default_tenant_id`. `§F`'s `{kind:"authenticated", …}`
   would parse nothing.
2. **The step-up code is `reauth_required`, not `reauthentication_required`**
   (`domain/account_service.py:207`, and `docs/api/error-codes.md:31`). The
   extras carry `reauth_window_seconds`, not `methods`.
3. **The MFA method literal is `recovery_code`, not `recovery`.**
4. **The mailed links are hash routes, and this SPA has no hash router.**
   `domain/compose.py:100,105` build `…/#/reset-password?token=…` and
   `…/#/account-recovery?token=…`. `web/` runs `BrowserRouter`, so both links
   currently land on `/`, get bounced to `/login` by `RequireAuth`, and the
   token is dropped on the floor. The reset link has never worked against
   this app — the hash form was written for the sibling Notes AI SPA. The
   fragment placement is deliberate and worth keeping (`compose.py:93-97`: a
   fragment never reaches the server, so the token stays out of every proxy
   access log and out of `Referer`), so the fix is a bridge that reads
   `location.hash` and never promotes the token into the path or query.

### Stale artefact

`docs/api/auth-service-openapi.json` predates A3/A5/B1b: it has no
`/auth/email/*`, no `/auth/reauth*`, no `/auth/mfa/totp/*`, no
`/auth/oauth/token`, and still lists the `/admin/users/*` routes B2 is meant
to remove. `types.ts` claims its DTOs are "verified against
docs/api/*-openapi.json snapshots". The new DTOs are therefore verified
against the **routers and `domain/transport.py`**, and the header comment now
says so. Regenerating the snapshot is auth-service work, not web work —
recorded under Debt.

## What was built

| Issue | Delivered |
| --- | --- |
| W1-01 | `http.ts`: `X-Client-Type: web` on every `auth`-base call, `X-Request-Id` (UUID v4) on every call and surfaced as `ApiError.requestId`; `setReauthHandler` + one retry on `403 reauth_required`; `Authorization` built once. Typed DTOs for every endpoint above; `api/auth.ts` grown to the full set. |
| W1-02 | `AuthContext`: `AuthResult` handling on `status`, `identity` / `memberships` / `activeTenantId`, `reauth()`, `signInWithEmailCode`, `completeMfa`. `AccountMenu` and `displayName` read `identity`. |
| W1-03 | `/login` (email → code), `CodeInput` (6 boxes, paste, auto-submit, shake), `/welcome`. |
| W1-04 | `/login/password`, `/login/mfa`, `/reset`, `/account-recovery`, and the hash-link bridge that makes the mailed links resolve. |
| W1-06 | Reauth dialog wired to the real `/auth/reauth/start` → `/auth/reauth` pair; `errorCopy.ts` covering every code in `docs/api/error-codes.md` these flows can raise; Vitest unit suite (63 tests, 4 files). |

### Files

New: `src/components/CodeInput.tsx`, `src/components/ReauthDialog.tsx`,
`src/lib/errorCopy.ts`, `src/lib/mailLink.ts`,
`src/pages/auth/{LoginShell,PasswordLoginPage,MfaPage,WelcomePage,ResetPasswordPage,AccountRecoveryPage}.tsx`,
`tests/{setup.ts,errorCopy.test.ts,transport.test.ts,codeInput.test.tsx,authContext.test.tsx}`.

Changed: `src/api/{http,auth,types}.ts`, `src/auth/AuthContext.tsx`,
`src/pages/LoginPage.tsx`, `src/App.tsx`, `src/main.tsx`,
`src/shell/AppShell.tsx`, `src/styles/{pages,components,shell}.css`,
`package.json`, `tsconfig.json`, `vite.config.ts`,
`.github/workflows/ci.yml`.

### Three things found while building, and what was done

1. **The mailed reset link had never worked here** (§B, finding 4).
   `src/lib/mailLink.ts` reads the fragment before the router mounts, maps
   `#/reset-password` → `/reset` and `#/account-recovery` →
   `/account-recovery`, and rewrites the address bar to the bare path. The
   token is held in a module variable for the life of the page load and is
   never in `location`, `history`, a query string or any storage — which
   keeps the property `compose.py` chose the fragment for.
2. **`web/` was not in CI at all.** No `npm ci`, no type-check, no build —
   its type errors only ever failed on somebody's laptop. A `web` job was
   added to `.github/workflows/ci.yml` (type-check, `npm test`, build). It
   checks out the whole repo because the error-copy test reads
   `docs/api/error-codes.md`.
3. **The seeded dev credential was printed on the login card in every
   build.** It now renders only under `import.meta.env.DEV`, on the
   password screen where it applies; `grep dev-password dist/` is empty
   after `npm run build`.

### Verification run here

- `npx tsc --noEmit` — clean.
- `npm test` — 63 passed, 4 files.
- `npm run build` — 89 modules, `dist/assets/index-*.js` 284 kB (88 kB gzip).
- `grep -rn db_user src/` — three hits, all inside `AuthContext` / `types.ts`
  with the comment explaining the fallback. `AppShell` reads `identity`.

## Not met

1. **The refresh ceiling (A2's remaining half).** Described above. Until
   `SessionService.refresh` and a native `/auth/refresh` exist, a native-mode
   sign-in does not survive a reload. Nothing in `web/` can fix it.
2. **W1-05 `/invite/:token` — not built.** There is no server. Writing a page
   against an invented `GET /invitations/:token` would produce a screen that
   compiles, renders, and is fiction. It waits for B1.
3. **`switchTenant` — not built.** `POST /auth/token` does not exist. The live
   `POST /tenants/{id}/switch` deliberately does **not** re-scope the token —
   its own docstring says the SPA must "re-authenticate to obtain a token
   scoped to this tenant". `memberships` are hydrated and exposed on the
   context so W2's switcher has its data the moment the endpoint lands.
4. **Playwright suite — not built.** `web/` has no browser-test harness, and
   the suite in §L needs the compose stack plus a mail sink exposing the last
   code; neither is running here. The Vitest units that do not need a server
   were written instead (DTO/no-`refresh_token`, error-map coverage driven by
   `docs/api/error-codes.md`, `CodeInput` paste/auto-submit). The Playwright
   specs stay owed.
5. **axe a11y check — not run** (same missing harness). The forms carry the
   `autocomplete` hints §I names, `role="alert"` on every error, a labelled
   `role="group"` around the code input with per-box `aria-label`s, and a
   `prefers-reduced-motion` opt-out of the shake — but that is an assertion,
   not a measurement.
6. **`eslint` — there is none.** The global DoD lists "`tsc`, `eslint` (web)";
   `web/` has no eslint config, no eslint dependency, and no CI step that ever
   ran one. `tsc --noEmit` (strict, with `noUnusedLocals` and
   `noUncheckedIndexedAccess`) and the production build are what this sprint
   can honestly claim. Standing up a lint config is its own change and would
   touch every existing file.

## Debt

- `docs/api/auth-service-openapi.json` is stale by three sprints. Regenerate
  it in the auth service, then re-verify `web/src/api/types.ts` against it.
- `POST /auth/password/*` is mounted only in keycloak mode and is backed by
  Keycloak's `set_password`. When A4 lands the native password surface, the
  `/reset` page's request shape must be re-checked — it is `{token,
  new_password}` today.
- `routers/me.py` reads the `users` table. When it grows `identity` and
  `memberships`, `AuthContext.hydrate` should prefer them over the
  `db_user` fallback it uses today; the shim is marked in the file.
- The `login-*` styles assumed one card of fixed height; the code step is
  taller. New rules were added rather than the existing ones changed.
