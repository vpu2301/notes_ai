-- Down: the index guards trashed notes again. Fails if a job is owned by
-- both a live note and a trashed one — resolve those rows first.
DROP INDEX IF EXISTS notes_source_asr_job_unique;
CREATE UNIQUE INDEX notes_source_asr_job_unique
    ON notes (tenant_id, source_asr_job_id)
    WHERE source_asr_job_id IS NOT NULL;
