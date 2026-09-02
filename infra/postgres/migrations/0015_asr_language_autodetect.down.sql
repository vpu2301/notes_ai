-- Rows submitted with `auto` cannot satisfy the old CHECK; pin them to
-- what was detected (or `uk`, the pre-migration default) before narrowing.
UPDATE transcription_jobs
SET language = COALESCE(
        CASE WHEN detected_language IN ('uk', 'en') THEN detected_language END, 'uk')
WHERE language NOT IN ('uk', 'en');

ALTER TABLE transcription_jobs
    DROP COLUMN IF EXISTS detected_language;
ALTER TABLE transcription_jobs
    DROP CONSTRAINT IF EXISTS transcription_jobs_language_check;
ALTER TABLE transcription_jobs
    ADD CONSTRAINT transcription_jobs_language_check
        CHECK (language IN ('uk', 'en'));
