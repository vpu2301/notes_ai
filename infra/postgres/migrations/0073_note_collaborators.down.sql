-- Reverse of 0073. `shared_with_ids` was never written after 0073, so grants
-- made since then are lost on rollback; the audit trail lists them.
DROP FUNCTION public.can_manage_note(uuid, uuid, uuid);
DROP FUNCTION public.grant_note_collaborator(uuid, uuid);
COMMENT ON COLUMN notes.shared_with_ids IS NULL;
ALTER TABLE notes DROP COLUMN transcript_shared;
DROP TABLE note_collaborators;
DROP TYPE note_collab_role;
