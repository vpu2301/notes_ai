-- 0026 — IDX-B1b: credentials for principals that are not people.
--
-- Two kinds, and the difference between them is the whole design:
--
--   device  — a meeting-room capture box. Belongs to exactly one
--             workspace, and its token carries that workspace's `tid`
--             taken from THIS ROW, never from the request. A device
--             cannot ask to be in another tenant because there is
--             nowhere in the grant for it to say so.
--   service — a machine calling the API on the platform's behalf. Not
--             tenant-owned (see the CHECK below), so its token is minted
--             against the platform tenant.
--
-- Unlike `identities`, device rows ARE tenant-scoped: a workspace's
-- owners need to see and manage their own rooms, and that is an
-- `app_role` read inside the tenant. Service rows have no tenant and are
-- therefore invisible to `app_role` entirely — the RLS predicate below
-- can never be true for them.

CREATE TABLE service_credentials (
    -- This becomes the token's `sub`. A UUID rather than a name, so a
    -- renamed room does not change who its recordings belong to.
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    kind          TEXT NOT NULL CHECK (kind IN ('service', 'device')),

    tenant_id     UUID REFERENCES tenants(id) ON DELETE RESTRICT,

    -- 'asr-worker', 'Room 4.02'. Shown in the management UI and in the
    -- audit trail; never used for authentication.
    name          TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),

    -- Fixed per kind by the CHECK below, so the grant set cannot be
    -- widened through the API. Adding a role to a device would need a
    -- migration and a review, which is the point.
    roles         TEXT[] NOT NULL,

    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'revoked')),

    created_by    UUID,
    last_used_at  TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A device without a workspace has no `tid` to put in its token; a
    -- service with one would look tenant-scoped while its grant is not.
    CONSTRAINT service_credentials_kind_tenant CHECK (
        (kind = 'device'  AND tenant_id IS NOT NULL) OR
        (kind = 'service' AND tenant_id IS NULL)
    ),
    CONSTRAINT service_credentials_roles CHECK (
        (kind = 'device'  AND roles = ARRAY['device']) OR
        (kind = 'service' AND roles = ARRAY['service'])
    )
);

-- "List this workspace's rooms" — the only query the management UI runs.
CREATE INDEX service_credentials_tenant_idx
    ON service_credentials (tenant_id)
    WHERE kind = 'device';

CREATE TRIGGER service_credentials_set_updated_at
    BEFORE UPDATE ON service_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT                         ON service_credentials TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON service_credentials TO tenant_writer;

ALTER TABLE service_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_credentials FORCE  ROW LEVEL SECURITY;

-- app_role reads its own tenant's devices. Service rows have a NULL
-- tenant_id, so this predicate is NULL for them and the row never
-- matches — machines that serve the platform are not a workspace's
-- business.
CREATE POLICY service_credentials_app_select ON service_credentials
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY service_credentials_app_restrictive ON service_credentials
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY service_credentials_writer_all ON service_credentials
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);


-- ── secrets ──────────────────────────────────────────────────────────
-- A credential may hold TWO live secrets at once. That is what makes a
-- room re-key possible without a visit: issue the new secret, deploy it
-- whenever the room is next free, and the old one keeps working until it
-- expires.
--
-- No `app_role` grant at all — not even SELECT. The hashes are the only
-- thing standing between a read-only database credential and the ability
-- to mint tokens for every room in the estate, and `app_role` is the role
-- every product service in the fleet connects as.

CREATE TABLE service_credential_secrets (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id  UUID NOT NULL REFERENCES service_credentials(id) ON DELETE CASCADE,

    -- sha256 hex of a 256-bit random secret. No KDF: the input is full
    -- entropy from `secrets.token_urlsafe`, so there is no dictionary to
    -- stretch against — unlike a password, which is why those get Argon2.
    secret_hash    TEXT NOT NULL,

    -- The first 8 characters after the `mdx_sk_` tag. Identification
    -- only: it lets an operator tell two live secrets apart in the UI and
    -- in a config file without ever seeing either in full.
    secret_prefix  TEXT NOT NULL,

    -- Set on the OLD secret when a rotation starts (default +24 h). NULL
    -- means "no scheduled end".
    expires_at     TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The grant looks a secret up BY HASH — there is no client id in the
-- lookup path until the row is found, so this index is the hot path.
CREATE UNIQUE INDEX service_credential_secrets_hash_uniq
    ON service_credential_secrets (secret_hash);

CREATE INDEX service_credential_secrets_credential_idx
    ON service_credential_secrets (credential_id)
    WHERE revoked_at IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON service_credential_secrets TO tenant_writer;

ALTER TABLE service_credential_secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_credential_secrets FORCE  ROW LEVEL SECURITY;

CREATE POLICY service_credential_secrets_writer_all ON service_credential_secrets
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);
