# ADR-0069 — A workspace is a tenant; one identity holds many, and the session carries which

**Status:** Accepted (dev/staging). The `native` flip and an organization layer are later decisions (W4). ·
**Date:** 2026-10-13 · **Implements:** Sprint W1 (workspaces & collaboration track) ·
**Related:** ADR-0047 (dual-issuer migration), ADR-0041 (CLI twins), concept §11
(`docs/sprints/workspaces-collab/01-concept.md`)

## Context

The schema has been many-to-many since 0001 (`tenant_memberships`), and the IDX track added
`identities`, `auth_sessions.tenant_id`, `tenants.kind` and `POST /auth/token`. All of it was
switched off: every deployment ran `MDX_IDP_MODE=keycloak`, where `tid` is a fixed Keycloak
attribute and nobody can hold two workspaces. `GET /auth/me.db_user`, the member roster and the
e-mail lookup still read the legacy single-tenant `users` row.

## Decision

1. **Workspace = tenant.** No `workspaces` table. Every RLS policy, object key, Redis key, job row
   and audit chain stays keyed by `tenant_id`. An organization, if it comes, is an optional parent
   (`tenants.organization_id NULL`), not a new isolation boundary.
2. **The native session model is the identity model.** Dev and staging run `dual`
   (`.env.example`, `docker-compose.override.yml`, `infra/k8s/notes/values.yaml`); prod pins
   `keycloak` explicitly until W4, because the chart's staging values would otherwise be inherited.
3. **The session is the only carrier of the current workspace.** A client learns it from sign-in
   or `POST /auth/token`, confirms it on every refresh (`TokenResponse.tenant_id`) and treats a
   mismatch as "the session moved". Web tabs share one session: the tab that switched wins; the
   others refuse non-`/auth/*` requests and show a reload strip.
4. **Personal is a kind, not a name.** Every active identity has exactly one `kind='personal'`
   membership, `owner`, `active` — healed by `ensure_personal_workspace` (which no longer counts
   team memberships), backfilled by `python -m auth_service.ops.ensure_personal`, asserted by
   `make check-identity-bridge`. Clients label it "Personal" whatever its `display_name`; its
   status cannot change (`409 personal_workspace`).
5. **`users` is derived, read-only data.** In dual/native mode `me.db_user` is computed from the
   active membership (deprecated; `active_membership` replaces it); the roster and e-mail lookup
   read `identities` on `tenant_writer`, and an e-mail resolves only to someone who already holds
   a membership in that workspace. `app_role` still cannot read `identities`.
6. **Roles:** `owner | admin | member | viewer | guest`; `assistant` is legacy. `guest` is
   decodable everywhere, offered nowhere, and has no ALLOW row until W3.
7. **Sockets are per (person, workspace).** The notification registry delivers a frame only to
   sockets opened in the frame's tenant; deep links carry `?ws=<tenant_id>`.
8. **Demo tenants are dev fixtures.** Files listed in `infra/postgres/migrations/DEV_ONLY` are
   recorded as `skipped` under `MDX_ENV=prod`; numbering stays dense.

## Options considered

- **B — organization = tenant, workspace = sub-scope** (Notion teamspaces). Moves the isolation
  boundary of every table and key before any customer asked for an organization. Rejected.
- **C — no organization ever.** A is C plus one nullable column later; A keeps the door open.
- **Per-tab sessions** (one `auth_sessions` row per browser tab). Multiplies sessions and breaks
  "sign out everywhere". Rejected. **`tid` in `localStorage`**: a tab could present a token for
  one workspace while believing it is in another. Rejected.
- **Re-implementing switching on a Keycloak attribute.** That is the single-tenant design the IDX
  track replaced. Rejected.

## Consequences

- `POST /admin/users/invite` answers `410 use_invitations` in dual/native mode; adding someone by
  e-mail works only for people already in the workspace until W2 ships invitations.
- `mdx_auth_me_legacy_db_user_total{client,source}` is the W4 gate for dropping `db_user`.
- Known debt: `calendar_connections` per workspace and MCP connectors per device are not
  workspace-independent; `tenant_of_sub()` still assumes one tenant per person.

## Revisit trigger

If W2 shows people creating one workspace and asking for shared folders instead, revisit B's
sub-scope as "shared spaces" inside a workspace.
