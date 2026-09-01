-- 0003 — `tenant_keks`: the wrapped per-tenant key-encryption-key store.
--
-- Audio and transcripts are envelope-encrypted; the per-tenant KEK is
-- wrapped by a master key and stored here. `crypto_writer` is the only
-- role permitted to INSERT/UPDATE (asr-service and asr-worker use this
-- dedicated role so a compromise of the broader app_role does not yield
-- write access to the wrapped-KEK store). SELECT is granted to app_role
-- (RLS-bound).

CREATE TABLE tenant_keks (
    tenant_id     UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE RESTRICT,
    wrapped_kek   BYTEA NOT NULL,
    kek_master_id TEXT  NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at    TIMESTAMPTZ
);

GRANT SELECT                 ON tenant_keks TO app_role;
GRANT SELECT, INSERT, UPDATE ON tenant_keks TO crypto_writer;

ALTER TABLE tenant_keks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_keks FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_keks_self_select ON tenant_keks
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- crypto_writer manages KEKs across tenants; it sets app.tenant_id
-- per-call like every other role.
CREATE POLICY tenant_keks_writer_select ON tenant_keks
    FOR SELECT TO crypto_writer
    USING (true);

CREATE POLICY tenant_keks_writer_insert ON tenant_keks
    FOR INSERT TO crypto_writer
    WITH CHECK (true);

CREATE POLICY tenant_keks_writer_update ON tenant_keks
    FOR UPDATE TO crypto_writer
    USING (true)
    WITH CHECK (true);

-- Defence in depth: a RESTRICTIVE policy preserves the invariant that
-- no role inserts a wrapped_kek with a master_id that's empty.
CREATE POLICY tenant_keks_master_id_nonempty ON tenant_keks
    AS RESTRICTIVE FOR ALL
    USING (length(kek_master_id) > 0)
    WITH CHECK (length(kek_master_id) > 0);
