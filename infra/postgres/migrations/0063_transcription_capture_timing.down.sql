ALTER TABLE transcription_jobs
    DROP COLUMN IF EXISTS first_frame_offset_ms,
    DROP COLUMN IF EXISTS record_pressed_at;
