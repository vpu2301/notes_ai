-- 0015 — Batch ASR: let the recording decide its own language.
--
-- Until now a job had to be pinned to `uk` or `en` at submit, and Whisper
-- was forced to decode in that language — a Ukrainian meeting submitted
-- under the English default came back as garbage. `language = 'auto'`
-- asks the worker to run language identification first and transcribe
-- in whatever it hears.
--
--   - `language` keeps meaning "what the caller asked for"; `auto` is
--     now a valid ask, and `de` joins so the batch row matches the
--     queue payload's vocabulary (libs/asr_models).
--   - `detected_language` is what the recording turned out to be in
--     (ISO 639-1, any Whisper language). The worker writes it when the
--     job completes; a pinned job echoes its pin. NULL while running or
--     for rows that predate this migration.

ALTER TABLE transcription_jobs
    DROP CONSTRAINT IF EXISTS transcription_jobs_language_check;
ALTER TABLE transcription_jobs
    ADD CONSTRAINT transcription_jobs_language_check
        CHECK (language IN ('auto', 'uk', 'en', 'de'));

ALTER TABLE transcription_jobs
    ADD COLUMN detected_language TEXT
        CONSTRAINT transcription_jobs_detected_language_check
        CHECK (detected_language IS NULL OR detected_language ~ '^[a-z]{2,3}$');

-- Completed pinned jobs already know their language.
UPDATE transcription_jobs
SET detected_language = language
WHERE status = 'complete' AND language <> 'auto' AND detected_language IS NULL;
