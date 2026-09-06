-- 0022: Postgres-backed job queue (Foundation plan decision 2; DEP-S1-03).
--
-- Canonical state for every new job type (assemble_capture, understand,
-- execute_action, embed, export_workspace, retention_sweep …) is THIS row —
-- a transport is never the source of truth. Claiming uses
-- FOR UPDATE SKIP LOCKED with a lease + heartbeat; a stale-lock reaper
-- re-queues jobs whose worker died.
--
-- `waiting_on_model` (DEP-S1): a scale-to-zero model endpoint waking up is
-- not a failure. A job parked in this state is re-claimed after `run_at`
-- WITHOUT consuming an attempt (see jobs_claim); the runner enforces the
-- 2 × cold_start_seconds budget, after which normal retry/backoff applies.
--
-- Tenancy: tenant-scoped RLS for app_role. Claiming has to see every
-- tenant's queue, so it goes through SECURITY DEFINER functions (the
-- 0005 asr_tenants_with_stale_jobs precedent) with a pinned search_path;
-- everything else a worker does to a job runs inside tenant_connection().

CREATE TABLE jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    kind             TEXT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                     ('queued', 'running', 'waiting_on_model', 'complete', 'failed', 'cancelled', 'dead')),
    priority         SMALLINT NOT NULL DEFAULT 0,
    attempts         SMALLINT NOT NULL DEFAULT 0,
    max_attempts     SMALLINT NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    leased_by        TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at     TIMESTAMPTZ,
    waiting_backend  TEXT,
    waiting_since    TIMESTAMPTZ,
    error_kind       TEXT,
    last_error       TEXT NOT NULL DEFAULT '',
    result           JSONB,
    idempotency_key  TEXT,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER jobs_set_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Same tenant + kind + key enqueued twice returns the first row (idempotent POST).
CREATE UNIQUE INDEX jobs_idempotency_idx
    ON jobs (tenant_id, kind, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
-- The claim scan: only claimable rows, in claim order.
CREATE INDEX jobs_claimable_idx
    ON jobs (kind, priority DESC, run_at)
    WHERE status IN ('queued', 'waiting_on_model');
CREATE INDEX jobs_tenant_idx
    ON jobs (tenant_id, created_at DESC);
CREATE INDEX jobs_lease_idx
    ON jobs (lease_expires_at)
    WHERE status = 'running';
CREATE INDEX jobs_waiting_idx
    ON jobs (waiting_backend, waiting_since)
    WHERE status = 'waiting_on_model';

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE  ROW LEVEL SECURITY;

CREATE POLICY jobs_tenant_select ON jobs
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY jobs_tenant_insert ON jobs
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY jobs_tenant_update ON jobs
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY jobs_tenant_delete ON jobs
    FOR DELETE TO app_role
    USING (false);  -- jobs are history; retention sweeps run as a job, not a DELETE
CREATE POLICY jobs_tenant_restrictive ON jobs
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON jobs TO app_role;

-- ── cross-tenant claim ──────────────────────────────────────────────
-- Leases up to `max_rows` claimable jobs of the given kinds to `worker`.
-- A job re-claimed from `waiting_on_model` does NOT consume an attempt:
-- the model endpoint waking up is not the job's fault.
CREATE OR REPLACE FUNCTION jobs_claim(
    kinds          TEXT[],
    worker         TEXT,
    lease_seconds  INTEGER,
    max_rows       INTEGER
)
RETURNS SETOF jobs
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    UPDATE jobs j
       SET status           = 'running',
           attempts         = CASE WHEN j.status = 'waiting_on_model' THEN j.attempts ELSE j.attempts + 1 END,
           leased_by        = worker,
           lease_expires_at = now() + make_interval(secs => lease_seconds),
           heartbeat_at     = now(),
           started_at       = COALESCE(j.started_at, now())
     WHERE j.id IN (
           SELECT c.id
             FROM jobs c
            WHERE c.status IN ('queued', 'waiting_on_model')
              AND c.run_at <= now()
              AND c.kind = ANY (kinds)
            ORDER BY c.priority DESC, c.run_at
            LIMIT max_rows
              FOR UPDATE SKIP LOCKED)
    RETURNING j.*;
$$;

-- Stale-lock reaper: a running job whose lease expired more than
-- `grace_seconds` ago goes back to the queue (its attempt was consumed).
-- Beyond max_attempts it is dead — a human looks, not a retry storm.
CREATE OR REPLACE FUNCTION jobs_reap_stale_leases(grace_seconds DOUBLE PRECISION)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n INTEGER;
BEGIN
    UPDATE jobs
       SET status     = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
           run_at     = now(),
           leased_by  = NULL,
           lease_expires_at = NULL,
           error_kind = 'worker_lost',
           last_error = 'lease expired without heartbeat',
           finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END
     WHERE status = 'running'
       AND lease_expires_at < now() - make_interval(secs => grace_seconds);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- Gauge input: jobs parked on a warming backend, across tenants.
CREATE OR REPLACE FUNCTION jobs_waiting_by_backend()
RETURNS TABLE (backend TEXT, waiting BIGINT, oldest_seconds DOUBLE PRECISION)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT waiting_backend,
           count(*),
           EXTRACT(EPOCH FROM (now() - min(waiting_since)))
      FROM jobs
     WHERE status = 'waiting_on_model'
     GROUP BY waiting_backend;
$$;

REVOKE ALL ON FUNCTION jobs_claim(TEXT[], TEXT, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION jobs_reap_stale_leases(DOUBLE PRECISION) FROM PUBLIC;
REVOKE ALL ON FUNCTION jobs_waiting_by_backend() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION jobs_claim(TEXT[], TEXT, INTEGER, INTEGER) TO app_role;
GRANT EXECUTE ON FUNCTION jobs_reap_stale_leases(DOUBLE PRECISION) TO app_role;
GRANT EXECUTE ON FUNCTION jobs_waiting_by_backend() TO app_role;
