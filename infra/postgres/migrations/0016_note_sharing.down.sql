DROP FUNCTION IF EXISTS public.resolve_note_share_link(text);
DROP TABLE IF EXISTS note_share_links;
DROP INDEX IF EXISTS notes_tenant_live_idx;
ALTER TABLE notes
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS shared_with_ids,
    DROP COLUMN IF EXISTS visibility;
DROP TYPE IF EXISTS note_visibility;
