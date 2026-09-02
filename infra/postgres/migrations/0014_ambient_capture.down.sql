ALTER TABLE dictation_sessions
    DROP COLUMN IF EXISTS device_name,
    DROP COLUMN IF EXISTS capture_source;
