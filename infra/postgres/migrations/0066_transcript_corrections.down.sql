-- Revert 0066: corrections go; transcripts read as the ASR artefact again.
DROP TABLE IF EXISTS transcript_corrections;
ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS corrections_rev;
ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS entity_unify_status;
