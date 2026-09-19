-- 0041 — Sprint 23: workspace sharing policy, verified recipients,
-- "what changed since you last looked", abuse reports.
--
-- `tenants.sharing_policy` is the admin's say over how notes leave the
-- workspace (shape validated by note-service `domain/sharing_policy.py`;
-- `{}` means every default). app_role may only SELECT `tenants`, so the
-- write goes through `set_tenant_sharing_policy`, a SECURITY DEFINER
-- helper that refuses any tenant but the connection's own.
--
-- `share_link_otps`: one live code per link when the policy asks
-- recipients to prove they hold the mailbox before they act. Hash only.
-- `share_abuse_reports`: "report this page" from the shared page.

ALTER TABLE tenants
    ADD COLUMN sharing_policy JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE note_share_links
    ADD COLUMN verified_at          TIMESTAMPTZ,
    ADD COLUMN last_seen_version_id UUID;

CREATE FUNCTION public.set_tenant_sharing_policy(p_tenant uuid, p_policy jsonb)
    RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
BEGIN
    IF p_tenant IS DISTINCT FROM current_setting('app.tenant_id', true)::uuid THEN
        RAISE EXCEPTION 'sharing policy: tenant mismatch';
    END IF;
    UPDATE public.tenants SET sharing_policy = p_policy, updated_at = now() WHERE id = p_tenant;
END
$$;
REVOKE ALL ON FUNCTION public.set_tenant_sharing_policy(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_tenant_sharing_policy(uuid, jsonb) TO app_role;

CREATE TABLE share_link_otps (
    link_id    UUID PRIMARY KEY REFERENCES note_share_links(id) ON DELETE RESTRICT,
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    code_hash  BYTEA NOT NULL,
    issued_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE share_link_otps ENABLE ROW LEVEL SECURITY;
ALTER TABLE share_link_otps FORCE  ROW LEVEL SECURITY;
CREATE POLICY share_link_otps_tenant_all ON share_link_otps
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON share_link_otps TO app_role;

CREATE TABLE share_abuse_reports (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    link_id    UUID NOT NULL REFERENCES note_share_links(id) ON DELETE RESTRICT,
    note_id    UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    reason     TEXT NOT NULL CHECK (reason IN ('spam', 'not_me', 'inaccurate', 'sensitive', 'other')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX share_abuse_reports_tenant_idx ON share_abuse_reports (tenant_id, created_at DESC);
ALTER TABLE share_abuse_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE share_abuse_reports FORCE  ROW LEVEL SECURITY;
CREATE POLICY share_abuse_reports_tenant_select ON share_abuse_reports
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY share_abuse_reports_tenant_insert ON share_abuse_reports
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY share_abuse_reports_tenant_delete ON share_abuse_reports
    FOR DELETE TO app_role
    USING (false);
CREATE POLICY share_abuse_reports_tenant_restrictive ON share_abuse_reports
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON share_abuse_reports TO app_role;
