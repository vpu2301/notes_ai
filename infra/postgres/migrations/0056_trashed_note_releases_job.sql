-- 0056 — A note in the bin lets go of its recording.
--
-- Since Sprint 34 the note exists from the first second of a meeting
-- (`POST /v1/notes/meeting`), and the transcription job is bound to it
-- while the recording is still running. When the author moves that
-- live, still-empty note to the bin before pressing Stop, the finished
-- transcript has nowhere to land: `POST /v1/notes/{id}/transcript` is a
-- 404 (the note is gone from every read path), and `from-transcript`
-- is a 409 `already_assigned`, because the unique index still counts
-- the trashed row. The recording is complete and unreachable.
--
-- The index now only guards LIVE notes. A trashed note keeps its
-- `source_asr_job_id` — the row and its versions stay, as the bin
-- promises — but it no longer owns the job, so a fresh note can be
-- drafted from the same transcript. The three "who owns this job"
-- lookups in note-service filter on `deleted_at IS NULL` to match.
DROP INDEX IF EXISTS notes_source_asr_job_unique;
CREATE UNIQUE INDEX notes_source_asr_job_unique
    ON notes (tenant_id, source_asr_job_id)
    WHERE source_asr_job_id IS NOT NULL AND deleted_at IS NULL;
