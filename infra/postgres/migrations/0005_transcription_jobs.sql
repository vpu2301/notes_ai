-- 0005 — `transcription_jobs`: durable record of every batch ASR job
-- submitted. The Redis Streams queue is the *transport*; this table is
-- the system of record (idempotency, audit, status, retries).
--
-- Lifecycle:
--   queued → running → complete | failed | cancelled
--
-- The worker uses (tenant_id, id) as the dedupe key against duplicate
-- delivery from Redis Streams (XAUTOCLAIM re-delivers on stuck consumers).
-- A row marked `complete` or `failed` short-circuits the worker.
--
-- The Whisper vocabulary hint (initial_prompt) is an optional free-text
-- value carried in request/config — there is no prompt catalogue table.

CREATE TABLE transcription_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    audio_id            UUID NOT NULL REFERENCES audio_files(id),
    requester_sub       UUID NOT NULL,
    language            TEXT NOT NULL CHECK (language IN ('uk','en')),
    model               TEXT NOT NULL DEFAULT 'large-v3',
    status              TEXT NOT NULL CHECK (status IN
                            ('queued','running','complete','failed','cancelled'))
                            DEFAULT 'queued',
    result_storage_uri  TEXT,
    error_kind          TEXT,
    error_detail        TEXT,
    cancel_requested    BOOLEAN NOT NULL DEFAULT false,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    attempts            SMALLINT NOT NULL DEFAULT 0,
    metadata            JSONB
);

CREATE INDEX transcription_jobs_tenant_status_idx ON transcription_jobs (tenant_id, status);
CREATE INDEX transcription_jobs_audio_idx        ON transcription_jobs (audio_id);
CREATE INDEX transcription_jobs_tenant_queued_idx
    ON transcription_jobs (tenant_id, queued_at DESC);
-- The reaper's scan predicate. Without it every sweep is a seq scan over
-- every job the tenant has ever submitted, on a table that only grows.
CREATE INDEX transcription_jobs_inflight_idx
    ON transcription_jobs (status, started_at, queued_at)
    WHERE status IN ('queued', 'running');

-- ── Grants ───────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON transcription_jobs TO app_role;

-- ── Row-level security ───────────────────────────────────────────────
ALTER TABLE transcription_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcription_jobs FORCE  ROW LEVEL SECURITY;

CREATE POLICY transcription_jobs_tenant_select ON transcription_jobs
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_jobs_tenant_insert ON transcription_jobs
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_jobs_tenant_update ON transcription_jobs
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_jobs_tenant_restrictive ON transcription_jobs
    AS RESTRICTIVE FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── Stranded-job reaper ─────────────────────────────────────────────
-- The reaper must answer "which tenants hold a job that no worker is
-- coming back for?" BEFORE it can open a tenant-scoped connection, and
-- that question is inherently cross-tenant. Asked on a plain app_role
-- connection it fails the quiet way: RLS evaluates
-- `current_setting('app.tenant_id', true)::uuid` with the setting unset
-- and either raises InvalidTextRepresentationError or filters every row
-- out — a reaper that "runs" and collects nothing.
--
-- What is being collected:
--   status='running' past the grace window — the worker marked the job
--   running and then died (SIGKILL, OOM kill, node eviction). Nothing
--   else revisits that row.
--   status='queued' past the (longer) grace window — the row committed
--   and the enqueue reported success, but the message did not survive to
--   be claimed (flushed Redis, trimmed stream, recreated consumer group).
--
-- Both leave a row that holds a slot in per_tenant_concurrent_jobs and
-- shows the user a job that is never going to resolve.

CREATE OR REPLACE FUNCTION asr_tenants_with_stale_jobs(
    running_grace_seconds DOUBLE PRECISION,
    queued_grace_seconds  DOUBLE PRECISION
)
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
-- Pinned search_path: a SECURITY DEFINER function without one is a
-- privilege-escalation vector (a caller-controlled search_path could
-- shadow `transcription_jobs` with their own table).
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT j.tenant_id
      FROM transcription_jobs j
     WHERE (j.status = 'running'
            AND j.started_at < now() - make_interval(secs => running_grace_seconds))
        OR (j.status = 'queued'
            AND j.queued_at  < now() - make_interval(secs => queued_grace_seconds));
$$;

REVOKE ALL ON FUNCTION asr_tenants_with_stale_jobs(DOUBLE PRECISION, DOUBLE PRECISION)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION asr_tenants_with_stale_jobs(DOUBLE PRECISION, DOUBLE PRECISION)
    TO app_role;
