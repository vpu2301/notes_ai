-- 0045 — Turn-level correction + capture context (Sprint 30).
--
-- Reassign edits (kind='reassign', moving turns to another speaker, a new
-- speaker or "unattributed") use the Sprint 28 overlay table. A move to a
-- speaker the system missed allocates a label: `creates_label` marks it.
--
-- Capture context is the snapshot a client had when the recording started
-- (from a calendar event): the invitee names offered as a picklist and
-- where the capture came from. The names are CONTENT — stored like
-- `speaker_names` on the tenant-scoped, RLS-protected row, never granted to
-- report roles, never in audit payloads.
--
-- `result_first_read_at` is set once, when the transcript is first opened:
-- the "opened" fact the weekly speaker report counts from (the report role
-- must not read the audit schema).

ALTER TABLE transcription_speaker_edits
    ADD COLUMN creates_label BOOLEAN NOT NULL DEFAULT false,
    ADD CONSTRAINT speaker_edits_reassign_shape CHECK (
        kind <> 'reassign'
        OR (segment_indices IS NOT NULL AND cardinality(segment_indices) BETWEEN 1 AND 500)
    );

ALTER TABLE transcription_jobs
    ADD COLUMN speaker_name_candidates JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(speaker_name_candidates) = 'array'),
    ADD COLUMN capture_context JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(capture_context) = 'object'),
    ADD COLUMN result_first_read_at TIMESTAMPTZ;
