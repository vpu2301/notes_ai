-- 0091 — Task P2a: the instructions box holds the writer's whole rules (the default file
-- is ~3 K chars; a workspace adding its own needs room), so the limit goes 8 000 → 12 000.
-- The API refuses longer texts (413 text_too_long) before the constraint is reached.

ALTER TABLE workspace_note_instructions
    DROP CONSTRAINT workspace_note_instructions_text_check,
    ADD CONSTRAINT workspace_note_instructions_text_check
        CHECK (char_length(text) BETWEEN 1 AND 12000);

ALTER TABLE note_instructions
    DROP CONSTRAINT note_instructions_text_check,
    ADD CONSTRAINT note_instructions_text_check
        CHECK (char_length(text) BETWEEN 1 AND 12000);
