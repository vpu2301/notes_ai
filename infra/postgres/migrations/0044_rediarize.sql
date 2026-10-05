-- 0044 — Speaker re-labelling (Sprint 29).
--
-- `POST /asr/jobs/{id}/rediarize` recomputes a complete job's speaker
-- labels from its stored audio and words (no ASR pass). The job's own
-- `status` stays `complete` throughout; the re-run has its own state here.
--
--   diarization_status  NULL until the first re-run (the initial
--                       diarization rides `status`), then the re-run's state.
--   diarization_error   JobErrorKind of a failed re-run, or `stranded`
--                       (the reaper), `enqueue_failed` (the API).
--   diarization_runs    re-runs requested; the API caps it per job.
--   previous_result_storage_uri / previous_speaker_names
--                       one-step undo: the labelling a re-run replaced.
--   diarization_updated_at
--                       last re-run transition — what the reaper's grace
--                       windows are measured against.
--   diarization_request_id
--                       the re-run request the row is waiting on. The worker
--                       claims, swaps and fails only with a matching id, so a
--                       stale queue message can never act for a newer request.
--
-- `diarization_rev` exists since 0043; a re-run and an undo each bump it,
-- which is what leaves older speaker edits inert.

ALTER TABLE transcription_jobs
    ADD COLUMN diarization_status TEXT
        CHECK (diarization_status IS NULL
               OR diarization_status IN ('queued', 'running', 'complete', 'failed')),
    ADD COLUMN diarization_error TEXT,
    ADD COLUMN diarization_runs SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN previous_result_storage_uri TEXT,
    ADD COLUMN previous_speaker_names JSONB,
    ADD COLUMN diarization_updated_at TIMESTAMPTZ,
    ADD COLUMN diarization_request_id UUID;

CREATE INDEX transcription_jobs_rediarize_active_idx
    ON transcription_jobs (diarization_updated_at)
    WHERE diarization_status IN ('queued', 'running');

-- The reaper's cross-tenant question (0005) also asks for stranded
-- re-runs: a worker that died mid re-run would otherwise leave the UI
-- showing "re-labelling…" forever. Same signature, same grace windows.
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
            AND j.queued_at  < now() - make_interval(secs => queued_grace_seconds))
        OR (j.diarization_status = 'running'
            AND j.diarization_updated_at < now() - make_interval(secs => running_grace_seconds))
        OR (j.diarization_status = 'queued'
            AND j.diarization_updated_at < now() - make_interval(secs => queued_grace_seconds));
$$;

REVOKE ALL ON FUNCTION asr_tenants_with_stale_jobs(DOUBLE PRECISION, DOUBLE PRECISION)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION asr_tenants_with_stale_jobs(DOUBLE PRECISION, DOUBLE PRECISION)
    TO app_role;
