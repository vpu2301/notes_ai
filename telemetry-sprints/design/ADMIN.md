# Admin & auth design

## 1. Web route `/admin/dashboard`

- Router: `web/src/App.tsx`. `/admin/sharing` (`:188`) already exists inside the signed-in app shell; `/admin/dashboard` is unused (the catch-all `*` at `:208` redirects it today).
- Add one route `/admin/dashboard` (and `/admin/dashboard/runs/:runId`) next to `/admin/sharing`, inside the same authenticated layout. New page components under `web/src/pages/admin/` (`TelemetryDashboardPage.tsx`, `TelemetryRunPage.tsx`) and a client module `web/src/api/telemetry.ts`. No existing route, guard or component changes behaviour.
- Guard: the page reads the JWT roles; without `platform_admin` it renders "Not available" (same pattern as `SettingsLayout` `activeRole` gating). Sidebar link shown only to `platform_admin` (no change for owner/admin, who keep `/admin/sharing`).
- URL: `http://localhost:5173/admin/dashboard` (Vite `strictPort` 5173).

## 2. Role

- There is **no** platform-wide admin today: tenant `owner/admin` map to `tenant_admin` (one workspace); `auditor` is a read-only tenant role (`libs/auth/src/auth/perms.py`).
- Add, additively, platform role **`platform_admin`** and permission `telemetry.read_all` in `libs/auth/src/auth/perms.py` (the matrix test requires an explicit row for every role × action — add rows for all roles). `tenant_admin` gets `telemetry.read` (own tenant, via recording ACL); other roles get `telemetry.read` only through the recording ACL (STORAGE.md §4).
- Storage of the role: new nullable column `identities.platform_role` (`platform_admin|null`) — additive; auth-service adds it to the token's `roles` when set. Keycloak-issued tokens never carry it (dev bootstrap is native-only).

## 3. Dev-only `admin` / `admin` bootstrap

The existing password login takes an `EmailStr` (`services/auth-service/src/auth_service/routers/password.py:58`), so a bare `admin` cannot sign in there, and changing that request model would change an existing endpoint's shape. Therefore:

- **Bootstrap** (auth-service startup, `main_deps`): if `ENVIRONMENT ∈ {development, dev, local}` (the repo's marker; `APP_ENV` does not exist) **and** `MDX_IDP_MODE ∈ {dual, native}` **and** no identity with email `admin@dev.notes-ai.test` exists → create it (display name "admin"; identities are e-mail keyed, there is no username column, so the dev login maps the username `admin` to this e-mail), password hash of `admin` written directly (bypassing `_reject_weak`, dev only), `platform_role = 'platform_admin'`, membership in no tenant required, `must_change_password = false`. Logged as `auth.dev_admin_bootstrapped` (no password in the log).
- **Login:** new endpoint `POST /auth/dev/admin-login {username, password}` → the same native session response as the password login (access token + `mdx_rt` cookie / `nrt_` for native clients). Registered **only** when the env check above passes; otherwise the route does not exist (404).
- The dashboard page, when unauthenticated in dev, shows a two-field form posting to that endpoint; in non-dev builds the form is not rendered and the normal sign-in is used.
- **Any other environment:** the bootstrap never runs; on every password login, if the submitted password is exactly `admin` or the identity is the dev `admin` identity, refuse with the generic invalid-credentials error and log `auth.dev_admin_refused` at WARNING (+ `mdx_auth_dev_admin_refused_total`). A startup check in non-dev logs ERROR if an `admin` identity with platform role exists.
- Documented in this file and in the README "Local development" section (Sprint 4).

## 4. Admin endpoints and middleware

Repo convention (no `/api` prefix; each service owns a prefix; admin lives at `/v1/admin/...` in note-service): the telemetry HTTP surface lives in **note-service**, which already owns the note/recording ACL (`domain/access.py`) and `/v1/admin/sharing`:

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /v1/telemetry/client-events` | any signed-in user; tenant from token; recording ACL check | client event ingest (Sprint 3) |
| `GET /v1/telemetry/runs?recording_id=` | recording ACL | runs of one recording |
| `GET /v1/telemetry/runs/{run_id}` | recording ACL | full run export (JSON, schema v1) |
| `GET /v1/telemetry/runs/{run_id}/report.md` | recording ACL | deterministic Markdown report |
| `GET /v1/admin/telemetry/runs` | `platform_admin` (`telemetry.read_all`) | all tenants, filter by status/stage/backend/date |

Reused middleware: `note_service.deps` bearer verification (multi-issuer `AUTH_ISSUERS_JSON`), `requires(...)` permission dependency, `RequestIDMiddleware`, existing rate limiting. The asr-service and workers write telemetry directly to Postgres through `libs/telemetry` (no HTTP hop).

## 6. As built (Sprint 4, 2026-10-22)

| Endpoint (note-service) | Permission | Notes |
|---|---|---|
| `GET /v1/telemetry/runs?recording_id=&status=&from=&to=&limit=&cursor=` | `telemetry.read` | keyset cursor (`submitted_at DESC, run id DESC`); without `recording_id` a member sees runs of recordings they submitted, a workspace admin the workspace, the platform admin every tenant |
| `GET /v1/telemetry/runs/{run_id}` | `telemetry.read` | schema-v1 export + `missing_measurements` |
| `GET /v1/telemetry/runs/{run_id}/report.md` | `telemetry.read` | `attachment; filename=diagnostics-<recording>-<run>.md` |
| `GET /v1/telemetry/recordings/{recording_id}/runs` | `telemetry.read` | initial + reprocesses, newest first |
| `GET /v1/admin/telemetry/overview?from=&to=` | `telemetry.read_all` | aggregates over at most the newest 500 runs of the period (`capped` says so) |

- Recording ACL for non-admins: requester, a note on the recording the caller can view
  (`domain/access.can_view`), or `tenant_admin`. Anything else is a 404.
- Cross-tenant reads: migration 0094 adds ids-only SECURITY DEFINER functions
  (`telemetry_tenants`, `telemetry_run_tenant`, `telemetry_recording_tenant`); the rows are
  then read per tenant through `tenant_connection`. No role bypasses RLS.
- `platform_admin` is in `KNOWN_ROLES` with exactly two grants (`telemetry.read`,
  `telemetry.read_all`); auth-service's role-edit API refuses to assign it
  (`ASSIGNABLE_ROLES`). `identities.platform_role` exists (0094) but nothing sets it yet.
- **Not built:** §3 (the dev bootstrap, `POST /auth/dev/admin-login`, the production refusal) and
  adding `platform_role` to session tokens. The permission classifier stopped the change to
  the token's `roles` claim, so it waits for the owner.
