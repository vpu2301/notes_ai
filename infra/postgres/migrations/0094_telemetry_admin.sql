-- Telemetry sprint 4: the platform admin and the cross-tenant reads its dashboard needs.
--
-- identities.platform_role: a platform-wide role, outside every workspace. When set, auth-service
-- adds it to the token's `roles` (libs/auth perms: `platform_admin` → telemetry.read_all). Only
-- the dev bootstrap sets it today (telemetry-sprints/design/ADMIN.md §3).
--
-- No role bypasses RLS. Like active_tenant_ids() (0001), these SECURITY DEFINER functions return
-- tenant ids only; note-service then reads each tenant's rows through tenant_connection, so
-- every telemetry row is still read under its own tenant's policies. The router authorises
-- (platform_admin) before it calls them.

ALTER TABLE identities ADD COLUMN platform_role TEXT
    CHECK (platform_role IN ('platform_admin'));

-- Tenants with at least one run submitted in [p_from, p_to).
CREATE FUNCTION telemetry_tenants(p_from TIMESTAMPTZ, p_to TIMESTAMPTZ)
    RETURNS SETOF UUID
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT tenant_id FROM telemetry_runs
     WHERE submitted_at >= p_from AND submitted_at < p_to
     ORDER BY tenant_id
$$;

CREATE FUNCTION telemetry_run_tenant(p_run_id UUID)
    RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$ SELECT tenant_id FROM telemetry_runs WHERE processing_run_id = p_run_id $$;

CREATE FUNCTION telemetry_recording_tenant(p_recording_id UUID)
    RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$ SELECT tenant_id FROM telemetry_runs WHERE recording_id = p_recording_id LIMIT 1 $$;

REVOKE ALL ON FUNCTION telemetry_tenants(TIMESTAMPTZ, TIMESTAMPTZ) FROM PUBLIC;
REVOKE ALL ON FUNCTION telemetry_run_tenant(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION telemetry_recording_tenant(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION telemetry_tenants(TIMESTAMPTZ, TIMESTAMPTZ) TO app_role;
GRANT EXECUTE ON FUNCTION telemetry_run_tenant(UUID) TO app_role;
GRANT EXECUTE ON FUNCTION telemetry_recording_tenant(UUID) TO app_role;
