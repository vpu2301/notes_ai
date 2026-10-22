DROP FUNCTION IF EXISTS telemetry_recording_tenant(UUID);
DROP FUNCTION IF EXISTS telemetry_run_tenant(UUID);
DROP FUNCTION IF EXISTS telemetry_tenants(TIMESTAMPTZ, TIMESTAMPTZ);
ALTER TABLE identities DROP COLUMN IF EXISTS platform_role;
