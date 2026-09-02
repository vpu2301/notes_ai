-- 0016 — Notes: delete, visibility, sharing.
--
-- Until now every note was readable by everyone in the workspace (with a
-- read purpose), could not be shared outside it, and could not be
-- removed — `cancel` was the only exit and it is a lifecycle state, not
-- a bin. Three additions:
--
--   - `visibility`: `private` (author team + people it was shared with)
--     or `workspace` (everyone in the tenant, as before). New notes are
--     private; rows that predate this migration keep the behaviour they
--     had by being backfilled to `workspace`.
--   - `shared_with_ids`: workspace members the author gave access to,
--     independent of visibility. Same shape as `co_author_ids`, but a
--     share grants reading only — sharing never makes someone an author.
--   - `deleted_at` / `deleted_by`: soft delete. Hard DELETE stays
--     forbidden by RLS (0009); a deleted note disappears from every
--     read path and its share links stop resolving, but the row and its
--     versions survive for audit and recovery.
--
-- `note_share_links` holds public "anyone with the link" tokens. Only a
-- hash is stored; the token itself is derived from the row id with a
-- server-side HMAC key, so a database read never yields a usable link.
-- `resolve_note_share_link` is the ONE way in for an anonymous reader:
-- SECURITY DEFINER, because the request carries no tenant context yet —
-- the function finds the tenant, and the service then opens an ordinary
-- RLS-scoped connection for it.

CREATE TYPE note_visibility AS ENUM ('private', 'workspace');

ALTER TABLE notes
    ADD COLUMN visibility      note_visibility NOT NULL DEFAULT 'private',
    ADD COLUMN shared_with_ids UUID[]          NOT NULL DEFAULT '{}',
    ADD COLUMN deleted_at      TIMESTAMPTZ,
    ADD COLUMN deleted_by      UUID;

-- Existing notes were visible to the whole workspace; keep that true.
UPDATE notes SET visibility = 'workspace';

CREATE INDEX notes_tenant_live_idx
    ON notes (tenant_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- ── Public share links ───────────────────────────────────────────────

CREATE TABLE note_share_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id         UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    -- sha256 of the token an anonymous reader presents.
    token_hash      TEXT NOT NULL UNIQUE,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID,
    last_viewed_at  TIMESTAMPTZ,
    view_count      INTEGER NOT NULL DEFAULT 0
);

-- One LIVE link per note; revoked ones stay as history.
CREATE UNIQUE INDEX note_share_links_live_idx
    ON note_share_links (note_id)
    WHERE revoked_at IS NULL;

ALTER TABLE note_share_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_share_links FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_share_links_tenant_select ON note_share_links
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_share_links_tenant_insert ON note_share_links
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_share_links_tenant_update ON note_share_links
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_share_links_tenant_delete ON note_share_links
    FOR DELETE TO app_role
    USING (false);  -- revocation is the delete

CREATE POLICY note_share_links_tenant_restrictive ON note_share_links
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON note_share_links TO app_role;

-- Anonymous entry point: token hash → (tenant, note), only for a live
-- link on a live note. Mirrors `tenant_of_sub` (0001): resolve the tenant
-- first, then let the caller open a normal tenant-scoped connection.
CREATE FUNCTION public.resolve_note_share_link(p_token_hash text)
    RETURNS TABLE (tenant_id uuid, note_id uuid, link_id uuid)
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT l.tenant_id, l.note_id, l.id
    FROM public.note_share_links l
    JOIN public.notes n ON n.id = l.note_id
    WHERE l.token_hash = p_token_hash
      AND l.revoked_at IS NULL
      AND (l.expires_at IS NULL OR l.expires_at > now())
      AND n.deleted_at IS NULL
$$;

REVOKE ALL ON FUNCTION public.resolve_note_share_link(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.resolve_note_share_link(text) TO app_role;
