ALTER TABLE note_generated_items
    DROP COLUMN IF EXISTS check_reason,
    DROP COLUMN IF EXISTS "check";
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_payload_check;
ALTER TABLE note_generated_items
    ADD CONSTRAINT note_generated_items_payload_check
    CHECK (payload IS NULL OR (jsonb_typeof(payload) = 'object' AND pg_column_size(payload) <= 2048));
