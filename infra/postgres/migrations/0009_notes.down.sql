DROP TABLE IF EXISTS note_synthesis_jobs;
DROP TABLE IF EXISTS audit.note_chain_failures;
ALTER TABLE notes DROP CONSTRAINT IF EXISTS notes_current_version_fk;
DROP TABLE IF EXISTS note_versions;
DROP TABLE IF EXISTS note_code_counters;
DROP TABLE IF EXISTS notes;
DROP TYPE IF EXISTS note_amendment_type;
DROP TYPE IF EXISTS note_status;
