-- 0053 — Sprint 37: which model processes this workspace's meetings.
--
-- Until now `Registry.resolve()` took its per-workspace settings from a
-- constant (`_platform_standard`): every workspace ran on the platform
-- default and nobody could choose otherwise, or find out who was
-- processing their data. The registry always had the seam
-- (`SettingsSource`); this is the table behind it.
--
-- `acknowledged_processors` is the point of the whole feature. A
-- workspace may only be routed to a processor an admin has explicitly
-- acknowledged by name and region — and the list shown to them is
-- computed from the SAME registry object that routes the calls
-- (`processors_for_env()`), so a config change cannot quietly add a
-- processor to someone's data path. Adding a backend to routing without
-- acknowledgement leaves that workspace on the tier it already had.

CREATE TABLE workspace_model_settings (
    tenant_id          UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL DEFAULT 'platform'
        CHECK (provider IN ('platform', 'anthropic', 'custom')),
    tier               TEXT NOT NULL DEFAULT 'standard'
        CHECK (tier IN ('standard', 'premium')),
    -- Off = no new generations. Existing notes keep every word they have.
    generation_enabled BOOLEAN NOT NULL DEFAULT true,
    -- [{name, region, acknowledged_by, acknowledged_at}] — who the admin
    -- agreed may process this workspace's meetings.
    acknowledged_processors JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(acknowledged_processors) = 'array'),
    -- NULL = the plan's default (tenants.plan_limits.ai_cents_per_month).
    monthly_budget_cents INTEGER CHECK (monthly_budget_cents IS NULL OR monthly_budget_cents >= 0),
    updated_by         UUID NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER workspace_model_settings_set_updated_at
    BEFORE UPDATE ON workspace_model_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Every member may SEE who processes their meetings; only an admin may
-- change it (the route also checks the role and requires MFA — this is
-- the second lock, not the only one).
ALTER TABLE workspace_model_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_model_settings FORCE  ROW LEVEL SECURITY;
CREATE POLICY workspace_model_settings_tenant_select ON workspace_model_settings
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_model_settings_tenant_insert ON workspace_model_settings
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_model_settings_tenant_update ON workspace_model_settings
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_model_settings_tenant_delete ON workspace_model_settings
    FOR DELETE TO app_role USING (false);
CREATE POLICY workspace_model_settings_tenant_restrictive ON workspace_model_settings
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON workspace_model_settings TO app_role;

-- Month-to-date AI spend per workspace. SECURITY INVOKER (the default)
-- so the caller's RLS on `model_usage` still applies: a view is not a
-- way around the tenant boundary.
CREATE VIEW model_usage_monthly AS
SELECT tenant_id,
       date_trunc('month', created_at) AS month,
       count(*)                        AS calls,
       sum(input_tokens)               AS input_tokens,
       sum(output_tokens)              AS output_tokens,
       sum(cost_cents_est)             AS cost_cents_est
FROM model_usage
GROUP BY 1, 2;
GRANT SELECT ON model_usage_monthly TO app_role;
