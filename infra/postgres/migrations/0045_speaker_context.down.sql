ALTER TABLE transcription_jobs
    DROP COLUMN IF EXISTS result_first_read_at,
    DROP COLUMN IF EXISTS capture_context,
    DROP COLUMN IF EXISTS speaker_name_candidates;

ALTER TABLE transcription_speaker_edits
    DROP CONSTRAINT IF EXISTS speaker_edits_reassign_shape,
    DROP COLUMN IF EXISTS creates_label;
