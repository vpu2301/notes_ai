-- 0064 — Sprint F2: a copy is evidence, not a statement; a bullet may have
-- sub-points.
--
-- A fact whose text is its quote copied (or that speaks in the speaker's own
-- voice) is kept — its quote is real and other lines cite it — but it is
-- never a line of the note. Such rows get placement 'evidence': stored with
-- the generation, served so the evidence popover can resolve what a line
-- cites, never rendered, never counted as written or suggested.
--
-- A topic bullet's sub-points are rows of their own (kind 'topic_bullet')
-- that name the bullet they sit under by its row key. One level only: the
-- engine never writes a sub-point of a sub-point. Tenant data under the
-- existing RLS; no backfill (older rows have no parent and no evidence).
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_placement_check;
ALTER TABLE note_generated_items ADD CONSTRAINT note_generated_items_placement_check
    CHECK (placement IN ('written', 'suggested', 'dismissed', 'superseded', 'evidence'));
ALTER TABLE note_generated_items
    ADD COLUMN parent_key TEXT
        CHECK (parent_key IS NULL OR char_length(parent_key) <= 64);
