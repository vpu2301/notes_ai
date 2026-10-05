-- Down: the table comes back empty (the rows were a stub's job history,
-- and nothing reads them), the grants go away.
DROP POLICY IF EXISTS model_usage_retention_select ON model_usage;
DROP POLICY IF EXISTS model_usage_retention_delete ON model_usage;
REVOKE SELECT, DELETE ON model_usage FROM tenant_writer;

DROP POLICY IF EXISTS jobs_retention_select ON jobs;
DROP POLICY IF EXISTS jobs_retention_delete ON jobs;
REVOKE SELECT, DELETE ON jobs FROM tenant_writer;

ALTER VIEW model_usage_monthly RESET (security_invoker);

CREATE TABLE IF NOT EXISTS note_synthesis_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    note_id       UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    request_hash  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    provider      TEXT NOT NULL DEFAULT 'mock',
    model         TEXT NOT NULL DEFAULT '',
    result        JSONB,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
ALTER TABLE note_synthesis_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_synthesis_jobs FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_synthesis_jobs_tenant_select ON note_synthesis_jobs
    FOR SELECT TO app_role USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_synthesis_jobs_tenant_insert ON note_synthesis_jobs
    FOR INSERT TO app_role WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_synthesis_jobs_tenant_delete ON note_synthesis_jobs
    FOR DELETE TO app_role USING (false);
CREATE POLICY note_synthesis_jobs_tenant_restrictive ON note_synthesis_jobs
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON note_synthesis_jobs TO app_role;
