DROP TABLE IF EXISTS note_relocations;
DROP INDEX IF EXISTS notes_visibility_source_idx;
ALTER TABLE notes
    DROP COLUMN IF EXISTS copied_from_tenant_id,
    DROP COLUMN IF EXISTS copied_from_note_id,
    DROP COLUMN IF EXISTS media_state,
    DROP COLUMN IF EXISTS visibility_source;
