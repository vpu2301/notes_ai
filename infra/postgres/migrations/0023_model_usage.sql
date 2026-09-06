-- 0023: model_usage ledger (DEP-S1-06).
--
-- One row per model call (chat completion, transcription, embedding),
-- written by the calling worker inside the job's tenant transaction via
-- the libs/models usage hook. Counts and identifiers only — never prompt,
-- transcript or output text. This is the only trustworthy input to tier
-- pricing and to the hosted break-even (DEP-S6); provider dashboards are
-- not the source of truth.
--
-- `tenant_id` is what the Foundation plan calls workspace_id: in this
-- schema the workspace IS the tenant (RLS on app.tenant_id).
--
-- Retention: 400 days (BE-S3 retention sweep). Append-only: app_role can
-- SELECT and INSERT, never UPDATE or DELETE.

CREATE TABLE model_usage (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    job_id          UUID,                       -- jobs.id when called from a job (no FK: jobs are swept)
    backend         TEXT NOT NULL,              -- config/models.yaml backend name
    model_id        TEXT NOT NULL,
    operation       TEXT NOT NULL,              -- chat.complete | asr.transcribe | embed
    ok              BOOLEAN NOT NULL,
    error_kind      TEXT,                       -- models.ErrorKind when not ok
    input_tokens    INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    audio_seconds   NUMERIC(12, 3) NOT NULL DEFAULT 0 CHECK (audio_seconds >= 0),
    latency_ms      INTEGER NOT NULL CHECK (latency_ms >= 0),
    attempts        SMALLINT NOT NULL DEFAULT 1,
    structured_mode TEXT,
    cost_cents_est  NUMERIC(12, 4) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX model_usage_tenant_idx  ON model_usage (tenant_id, created_at);
CREATE INDEX model_usage_backend_idx ON model_usage (backend, created_at);

ALTER TABLE model_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_usage FORCE  ROW LEVEL SECURITY;

CREATE POLICY model_usage_tenant_select ON model_usage
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY model_usage_tenant_insert ON model_usage
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY model_usage_tenant_update ON model_usage
    FOR UPDATE TO app_role
    USING (false);   -- append-only ledger
CREATE POLICY model_usage_tenant_delete ON model_usage
    FOR DELETE TO app_role
    USING (false);   -- retention sweep runs as a privileged job
CREATE POLICY model_usage_tenant_restrictive ON model_usage
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON model_usage TO app_role;

-- Daily rollup. security_invoker so the view runs under the caller's RLS
-- (a plain view would execute as its owner and bypass tenant policies).
CREATE VIEW model_usage_daily
WITH (security_invoker = true) AS
    SELECT date_trunc('day', created_at)          AS day,
           tenant_id,
           backend,
           model_id,
           operation,
           count(*)                               AS calls,
           count(*) FILTER (WHERE NOT ok)         AS failures,
           sum(input_tokens)                      AS input_tokens,
           sum(output_tokens)                     AS output_tokens,
           sum(audio_seconds)                     AS audio_seconds,
           sum(cost_cents_est)                    AS cost_cents_est,
           avg(latency_ms)::INTEGER               AS latency_ms_avg
      FROM model_usage
     GROUP BY 1, 2, 3, 4, 5;

GRANT SELECT ON model_usage_daily TO app_role;
