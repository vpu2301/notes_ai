-- 0063 — Sprint F1: when the person pressed Record, and how long the first
-- audio frame took.
--
-- A transcript that starts 45 s into the meeting has three possible causes:
-- audio that never reached the file, speech VAD did not hear, and speech the
-- decoder replaced with its prompt. The first one is only visible to the
-- client, so the client reports it at upload: the wall-clock moment of the
-- Record press and the milliseconds until the first buffer was written. The
-- worker names a leading stretch that long `no_audio`; support reads both
-- off the job. Nullable: older clients send neither. Tenant data under the
-- existing RLS, erased with the job. No backfill, no index.
ALTER TABLE transcription_jobs
    ADD COLUMN record_pressed_at TIMESTAMPTZ,
    ADD COLUMN first_frame_offset_ms INTEGER
        CHECK (first_frame_offset_ms IS NULL OR first_frame_offset_ms BETWEEN 0 AND 600000);
