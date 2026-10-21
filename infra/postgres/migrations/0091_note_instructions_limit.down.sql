-- 0091 down: the 8 000-char limit of 0080/0083. Fails while a longer text is stored.

ALTER TABLE workspace_note_instructions
    DROP CONSTRAINT workspace_note_instructions_text_check,
    ADD CONSTRAINT workspace_note_instructions_text_check
        CHECK (char_length(text) BETWEEN 1 AND 8000);

ALTER TABLE note_instructions
    DROP CONSTRAINT note_instructions_text_check,
    ADD CONSTRAINT note_instructions_text_check
        CHECK (char_length(text) BETWEEN 1 AND 8000);
