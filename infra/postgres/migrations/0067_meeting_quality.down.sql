DROP POLICY IF EXISTS funnel_reader_select ON transcript_corrections;

REVOKE SELECT (id, tenant_id, job_id, source, status, confidence, created_at, updated_at)
    ON transcript_corrections FROM funnel_reader;
REVOKE SELECT (job_id, step, windows_total, windows_done, windows_failed, prompt_version,
               backend, model_id, transcript_rev, error_kind)
    ON note_generations FROM funnel_reader;
REVOKE SELECT (language, model, detected_language, queued_at, started_at, error_kind, quality,
               entity_unify_status, corrections_rev)
    ON transcription_jobs FROM funnel_reader;

ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS quality;
