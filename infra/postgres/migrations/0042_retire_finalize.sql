-- 0042 — Finalize is gone.
--
-- A note is a living document: it autosaves, it can be shared at any
-- time, and it can be cancelled. The draft → finalized → amended
-- lifecycle, its validation, the one-hour revert window and the draft
-- watermark are removed from the product. Every note that was frozen
-- by that lifecycle becomes editable again; `finalized_at` is kept as
-- history and never set again. The status CHECK keeps the old values so
-- nothing has to be rewritten; new rows are only ever `draft` or
-- `cancelled`.

-- 0009 tied `finalized_at` to the status; a draft with a historical
-- `finalized_at` is exactly what this migration produces, so the rule
-- goes before the rows move.
ALTER TABLE notes DROP CONSTRAINT IF EXISTS notes_status_finalized_has_ts;

UPDATE notes
SET status = 'draft', updated_at = now()
WHERE status IN ('finalized', 'amended');
