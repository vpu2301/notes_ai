-- 0018 — Speaker naming for diarized batch jobs.
--
-- Diarization produces neutral labels (SPEAKER_1..N); the platform never
-- guesses who a voice belongs to (ADR-0034). People do: after a meeting
-- someone renames "Speaker 2" to "Mark", and every surface that shows
-- the transcript — the web app, the desktop app, the note built from it
-- — should agree from then on. So the mapping lives on the job row
-- (`PUT /asr/jobs/{id}/speakers`) and is merged into every read of the
-- transcript, rather than each client remembering its own names.
--
--   { "SPEAKER_1": "Mark", "SPEAKER_2": "Olena" }
--
-- Keys are neutral labels; values are the display names. A label with no
-- entry renders under its default ("Speaker 1"). Empty for undiarized
-- jobs and for every row that predates this migration.

ALTER TABLE transcription_jobs
    ADD COLUMN speaker_names JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT transcription_jobs_speaker_names_object_check
        CHECK (jsonb_typeof(speaker_names) = 'object');
