-- 0090 — Sprint P3: the optional check call's verdict on a written item (a mark, never a
-- deletion): ``check`` is ok | unsupported, ``check_reason`` the model's one line (content).
-- Nullable: NULL = not checked (the flag was off, or the row is older).

ALTER TABLE note_generated_items
    ADD COLUMN "check" text NULL CHECK ("check" IN ('ok', 'unsupported')),
    ADD COLUMN check_reason text NULL;

-- The worker marks rows after writing them.
GRANT UPDATE ON note_generated_items TO app_role;

-- P3: ``payload`` now carries the cited turns (up to 8 excerpts of ≤ ~1.4 KB); the 2 KB
-- cap from 0065 (figure fields) is widened to 16 KB.
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_payload_check;
ALTER TABLE note_generated_items
    ADD CONSTRAINT note_generated_items_payload_check
    CHECK (payload IS NULL OR (jsonb_typeof(payload) = 'object' AND pg_column_size(payload) <= 16384));
