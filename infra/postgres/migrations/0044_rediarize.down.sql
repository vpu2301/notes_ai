-- Restore the 0005 body of the reaper's function before its columns go.
CREATE OR REPLACE FUNCTION asr_tenants_with_stale_jobs(
    running_grace_seconds DOUBLE PRECISION,
    queued_grace_seconds  DOUBLE PRECISION
)
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
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

DROP INDEX IF EXISTS transcription_jobs_rediarize_active_idx;
ALTER TABLE transcription_jobs
    DROP COLUMN IF EXISTS diarization_request_id,
    DROP COLUMN IF EXISTS diarization_updated_at,
    DROP COLUMN IF EXISTS previous_speaker_names,
    DROP COLUMN IF EXISTS previous_result_storage_uri,
    DROP COLUMN IF EXISTS diarization_runs,
    DROP COLUMN IF EXISTS diarization_error,
    DROP COLUMN IF EXISTS diarization_status;
