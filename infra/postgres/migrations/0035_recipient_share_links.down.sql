-- Restores 0016's one-live-link-per-note rule. Refuses to run while any
-- note holds more than one live link: silently dropping recipient links
-- would revoke what a client is holding, and picking one to keep is not
-- a decision a migration should make. Revoke them first.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM note_share_links
        WHERE revoked_at IS NULL
        GROUP BY note_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'note_share_links: a note has more than one live link; '
            'revoke recipient links before rolling back 0035';
    END IF;
END $$;

DROP INDEX IF EXISTS note_share_links_note_live_idx;
DROP INDEX IF EXISTS note_share_links_live_public_idx;
CREATE UNIQUE INDEX note_share_links_live_idx
    ON note_share_links (note_id)
    WHERE revoked_at IS NULL;

ALTER TABLE note_share_links
    DROP COLUMN IF EXISTS ref_code,
    DROP COLUMN IF EXISTS cta_clicked_at,
    DROP COLUMN IF EXISTS first_viewed_at,
    DROP COLUMN IF EXISTS draft_acknowledged,
    DROP COLUMN IF EXISTS recipient_email,
    DROP COLUMN IF EXISTS label,
    DROP COLUMN IF EXISTS kind;

DROP TYPE IF EXISTS share_link_kind;
