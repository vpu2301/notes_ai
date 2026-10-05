-- 0047 — How each speaker name came about (Sprint 31).
--
-- label → "typed" | "picklist" | "channel" | "suggestion" | "cleared".
-- "channel" is the one name the platform sets without a click: on a
-- dual-channel capture with exactly one local speaker, that speaker is
-- named after the account owner (ADR-0053, a scoped exception to
-- ADR-0034). "cleared" records that a person removed such a name, so a
-- re-run never puts it back. Values are vocabulary, not content; the
-- names themselves stay in `speaker_names`.

ALTER TABLE transcription_jobs
    ADD COLUMN speaker_name_sources JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(speaker_name_sources) = 'object');
