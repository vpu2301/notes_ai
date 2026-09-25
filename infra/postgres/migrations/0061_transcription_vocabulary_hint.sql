-- 0061 — Sprint I2 T2: what the transcriber was told is stored with the job.
--
-- The 2026-09-25 incident (docs/security/2026-09-25-isolation-audit.md,
-- F-1) could not say from the database which vocabulary a job had been
-- given: the hint travelled on the queue message only. From now on the
-- exact string sent as Whisper's prompt is on the job row, tenant data
-- under the existing RLS, erased with the job, shown on the job to its
-- own tenant. NULL for jobs before this column and for jobs sent without
-- a hint. No backfill (the queue entries are not a record), no index.
ALTER TABLE transcription_jobs
    ADD COLUMN vocabulary_hint TEXT
        CHECK (vocabulary_hint IS NULL OR char_length(vocabulary_hint) <= 2000);
