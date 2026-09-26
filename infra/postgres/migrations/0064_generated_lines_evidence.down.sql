-- Revert 0064. Evidence rows go (they were never lines); sub-point rows
-- lose their parent and read as ordinary bullets.
DELETE FROM note_generated_items WHERE placement = 'evidence';
ALTER TABLE note_generated_items DROP COLUMN IF EXISTS parent_key;
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_placement_check;
ALTER TABLE note_generated_items ADD CONSTRAINT note_generated_items_placement_check
    CHECK (placement IN ('written', 'suggested', 'dismissed', 'superseded'));
