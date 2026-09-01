-- 0001 — identity & tenancy: `tenants`, `users`, `tenant_memberships`,
-- plus the two cross-tenant helper functions every background job relies on.
--
-- A tenant is a company/workspace (multi-tenant isolation unit). Row-level
-- security ensures `app_role` connections, scoped via `app.tenant_id`, can
-- reach their own tenant's rows and nothing else. `tenant_writer`
-- (auth-service) has full CRUD because tenant creation has no incumbent
-- tenant context.
--
-- Every user-schema table in this baseline follows the same RLS doctrine:
--   * ENABLE + FORCE row level security (a forgotten policy fails closed);
--   * PERMISSIVE per-command policies scoped to app.tenant_id;
--   * a RESTRICTIVE defence-in-depth policy so a future PERMISSIVE policy
--     added too loosely still cannot cross the tenant boundary.

CREATE TABLE tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    locale       TEXT NOT NULL DEFAULT 'en',
    timezone     TEXT NOT NULL DEFAULT 'UTC',
    status       TEXT NOT NULL CHECK (status IN ('active','suspended','dissolved'))
                 DEFAULT 'active',

    -- Organisation profile / branding (feeds branded PDF headers and the
    -- workspace settings page).
    legal_name          TEXT    NOT NULL DEFAULT '',
    slug                TEXT,
    logo_url            TEXT    NOT NULL DEFAULT '',
    logo_bytes          BYTEA,
    logo_content_type   TEXT    NOT NULL DEFAULT '',
    contact_email       TEXT    NOT NULL DEFAULT '',
    phone_number        TEXT    NOT NULL DEFAULT '',
    website             TEXT    NOT NULL DEFAULT '',
    address_line1       TEXT    NOT NULL DEFAULT '',
    address_line2       TEXT    NOT NULL DEFAULT '',
    postal_code         TEXT    NOT NULL DEFAULT '',
    city                TEXT    NOT NULL DEFAULT '',
    state_or_region     TEXT    NOT NULL DEFAULT '',
    country             TEXT    NOT NULL DEFAULT '',
    tax_id              TEXT    NOT NULL DEFAULT '',
    registration_number TEXT    NOT NULL DEFAULT '',
    -- Simple toggle mirroring the finer-grained `status` lifecycle column;
    -- background sweeps read this.
    is_active           BOOLEAN NOT NULL DEFAULT true,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bound the inline logo so a runaway upload can't bloat the row / TOAST.
    CONSTRAINT tenants_logo_size_chk
        CHECK (logo_bytes IS NULL OR octet_length(logo_bytes) <= 2 * 1024 * 1024)
);

-- Slug is a stable, URL-safe handle. Unique when present.
CREATE UNIQUE INDEX tenants_slug_unique ON tenants (slug) WHERE slug IS NOT NULL;

-- Trigger to keep `updated_at` current. Lives at schema level so subsequent
-- migrations can reuse the same function.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tenants_set_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Table-level grants. RLS is the row filter on top.
GRANT SELECT                         ON tenants TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO tenant_writer;

-- Enable RLS and FORCE it so even the table owner is subject to policies
-- in normal application traffic (only the superuser can bypass).
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE  ROW LEVEL SECURITY;

-- `app_role` can read its own tenant only.
CREATE POLICY tenants_self_select ON tenants
    FOR SELECT TO app_role
    USING (id = current_setting('app.tenant_id', true)::uuid);

-- `tenant_writer` has full CRUD; used exclusively by auth-service for
-- tenant onboarding and lifecycle changes.
CREATE POLICY tenants_writer_all ON tenants
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);

-- RESTRICTIVE defence-in-depth: even if a future PERMISSIVE policy is added
-- too loosely, app_role traffic can still only ever touch its own tenant
-- row. Scoped TO app_role only — tenant_writer onboarding deliberately has
-- no incumbent tenant context and must remain unrestricted.
CREATE POLICY tenants_app_restrictive ON tenants
    AS RESTRICTIVE FOR ALL TO app_role
    USING (id = current_setting('app.tenant_id', true)::uuid);

-- ── users ───────────────────────────────────────────────────────────
-- Per-tenant principals. The primary key is the Keycloak `sub` UUID — the
-- DB row and the IdP identity are 1:1, so there is no drift on log/audit
-- joins.

CREATE TABLE users (
    sub             UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    email           TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN
                        ('tenant_admin','member','viewer','auditor','service')),
    status          TEXT NOT NULL CHECK (status IN
                        ('invited','active','suspended','deactivated'))
                    DEFAULT 'invited',
    mfa_enrolled_at TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

CREATE INDEX users_tenant_idx ON users(tenant_id);

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON users TO app_role, tenant_writer;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE  ROW LEVEL SECURITY;

-- PERMISSIVE: app_role can act on users in its own tenant.
CREATE POLICY users_app_role_tenant ON users
    FOR ALL TO app_role
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- PERMISSIVE: tenant_writer scopes to the tenant set on the connection
-- (auth-service must SET app.tenant_id before user CRUD).
CREATE POLICY users_writer_tenant ON users
    FOR ALL TO tenant_writer
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- RESTRICTIVE: defence in depth for reads AND writes.
CREATE POLICY users_tenant_restrictive ON users
    AS RESTRICTIVE FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── tenant_memberships ──────────────────────────────────────────────
-- Many-to-many link between a Keycloak principal (`user_sub`) and a
-- tenant, carrying a management-facing role. `users` stays the per-tenant
-- principal record (sub is its PK, so a sub has ONE users row / home
-- tenant); membership is the broader authorization record for "which
-- workspaces may this sub reach". Cross-tenant reads (a user's own
-- membership list) run on the unrestricted `tenant_writer` role inside
-- auth-service, exactly like tenant onboarding does.

CREATE TABLE tenant_memberships (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The Keycloak principal. Not an FK to `users.sub`: a membership can
    -- exist for a sub whose per-tenant `users` row lives in a different
    -- tenant (the whole point of multi-tenant access).
    user_sub    UUID NOT NULL,

    -- Management-facing role. Distinct from the platform RBAC roles carried
    -- in the JWT (tenant_admin/member/viewer/auditor); this drives the
    -- workspace-members UI and maps to the platform roles at the service
    -- layer.
    role        TEXT NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('owner', 'admin', 'member',
                                    'assistant', 'viewer')),

    status      TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'invited', 'suspended')),

    invited_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One membership row per (tenant, principal).
    UNIQUE (tenant_id, user_sub)
);

CREATE INDEX tenant_memberships_tenant_idx ON tenant_memberships (tenant_id, role);
-- Drives the "workspaces available to me" lookup (all tenants for one sub).
CREATE INDEX tenant_memberships_user_idx ON tenant_memberships (user_sub);

CREATE TRIGGER tenant_memberships_set_updated_at
    BEFORE UPDATE ON tenant_memberships
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT                         ON tenant_memberships TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_memberships TO tenant_writer;

ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_memberships FORCE  ROW LEVEL SECURITY;

-- app_role: read the roster of the currently-scoped tenant only.
CREATE POLICY tenant_memberships_app_select ON tenant_memberships
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- tenant_writer: full CRUD across tenants (member management + the
-- cross-tenant membership list). Mirrors `tenants_writer_all`.
CREATE POLICY tenant_memberships_writer_all ON tenant_memberships
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);

CREATE POLICY tenant_memberships_app_restrictive ON tenant_memberships
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── Cross-tenant helper functions ───────────────────────────────────
-- SECURITY DEFINER runs as the owner and is the ONLY sanctioned way to see
-- across tenants. Each function is deliberately narrow and leaks nothing
-- but the ids the caller needs; the caller still opens a tenant-scoped
-- connection per tenant to do the actual work.

-- Resolve a user's tenant from their `sub` without an incumbent tenant
-- context (refresh-replay detection has only the consumed refresh token,
-- which carries `sub` but not the custom `tid` claim).
CREATE FUNCTION public.tenant_of_sub(p_sub uuid)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT tenant_id FROM public.users WHERE sub = p_sub
$$;

REVOKE ALL ON FUNCTION public.tenant_of_sub(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tenant_of_sub(uuid) TO app_role;

-- Active-tenant enumeration for in-process scheduled jobs (idle-draft
-- cleanup and friends): `tenants` is RLS-FORCEd to self-select for
-- app_role, so a sweeping job under app_role would otherwise see nothing.
CREATE FUNCTION public.active_tenant_ids()
    RETURNS SETOF uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT id FROM public.tenants
    WHERE is_active = true
    ORDER BY id
$$;

REVOKE ALL ON FUNCTION public.active_tenant_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.active_tenant_ids() TO app_role;
