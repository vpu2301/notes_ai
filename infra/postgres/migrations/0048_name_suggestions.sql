-- 0048 — Name suggestions (Sprint 32).
--
-- Suggestions are computed at read time and never stored; only a person's
-- "no" is: the (label, name) pairs dismissed for this job, so a dismissed
-- suggestion never comes back. Names are content — tenant-scoped row,
-- never granted to report roles, never audited. `speaker_name_sources`
-- already exists (0047, Sprint 31).

ALTER TABLE transcription_jobs
    ADD COLUMN dismissed_name_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(dismissed_name_suggestions) = 'array');
