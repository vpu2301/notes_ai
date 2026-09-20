DROP POLICY IF EXISTS funnel_reader_select ON transcription_speaker_edits;
DROP POLICY IF EXISTS funnel_reader_select ON transcription_jobs;
ALTER POLICY transcription_speaker_edits_tenant_restrictive ON transcription_speaker_edits
    TO PUBLIC;
ALTER POLICY transcription_jobs_tenant_restrictive ON transcription_jobs TO PUBLIC;
REVOKE SELECT (id, tenant_id, job_id, result_rev, seq, kind, from_label, to_label,
               segment_indices, created_at, reverted_at, creates_label)
    ON transcription_speaker_edits FROM funnel_reader;
REVOKE SELECT (id, tenant_id, status, finished_at, result_first_read_at, metadata,
               diarization_rev, diarization_runs, capture_context)
    ON transcription_jobs FROM funnel_reader;
