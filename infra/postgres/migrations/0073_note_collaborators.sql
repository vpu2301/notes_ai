-- 0073 — Per-note roles (W3, ADR-0071). `note_collaborators` replaces
-- `notes.shared_with_ids` in code: one row per (note, person) with a role
-- view | comment | edit. Today's sharees could edit, so the backfill keeps
-- them at `edit`. The array stays (unwritten) for rollback; W4 drops it.

CREATE TYPE note_collab_role AS ENUM ('view', 'comment', 'edit');

CREATE TABLE note_collaborators (
    note_id     UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_sub    UUID NOT NULL,
    role        note_collab_role NOT NULL,
    granted_by  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, user_sub)
);
CREATE INDEX note_collaborators_user_idx ON note_collaborators (tenant_id, user_sub);

ALTER TABLE note_collaborators ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_collaborators FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_collaborators_tenant_select ON note_collaborators
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_collaborators_tenant_insert ON note_collaborators
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_collaborators_tenant_update ON note_collaborators
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Revoke is a hard delete; the audit trail carries the history.
CREATE POLICY note_collaborators_tenant_delete ON note_collaborators
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_collaborators_tenant_restrictive ON note_collaborators
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- auth-service reads across tenants (guest sweeper) like `tenant_memberships`.
CREATE POLICY note_collaborators_writer_all ON note_collaborators
    FOR ALL TO tenant_writer USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON note_collaborators TO app_role;
GRANT SELECT ON note_collaborators TO tenant_writer;

ALTER TABLE notes
    ADD COLUMN transcript_shared BOOLEAN NOT NULL DEFAULT false;   -- "Include transcript" for view/comment/guest

-- Backfill (the migration runner is the superuser, so RLS does not narrow it).
INSERT INTO note_collaborators (note_id, tenant_id, user_sub, role, granted_by)
SELECT n.id, n.tenant_id, s.sub, 'edit', n.primary_author_id
FROM notes n, unnest(n.shared_with_ids) AS s(sub)
ON CONFLICT DO NOTHING;

COMMENT ON COLUMN notes.shared_with_ids IS 'DEPRECATED W3: read note_collaborators; dropped in W4';

-- The one sanctioned cross-service write (W3): auth-service, on accepting a
-- note invitation (W2 `tenant_invitations.note_id`), grants the collaborator
-- row. SECURITY DEFINER, so it checks everything itself: an ACCEPTED
-- invitation by this identity for a live note in the invitation's tenant.
-- Returns false (nothing written) when the note is gone.
CREATE FUNCTION public.grant_note_collaborator(p_invitation uuid, p_sub uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    inv record;
BEGIN
    SELECT i.tenant_id, i.note_id, i.note_role, i.invited_by INTO inv
      FROM tenant_invitations i
     WHERE i.id = p_invitation AND i.accepted_by = p_sub AND i.accepted_at IS NOT NULL
       AND i.note_id IS NOT NULL;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM notes n
                    WHERE n.id = inv.note_id AND n.tenant_id = inv.tenant_id
                      AND n.deleted_at IS NULL) THEN
        RETURN false;
    END IF;
    INSERT INTO note_collaborators (note_id, tenant_id, user_sub, role, granted_by)
    VALUES (inv.note_id, inv.tenant_id, p_sub, inv.note_role::note_collab_role, inv.invited_by)
    ON CONFLICT (note_id, user_sub) DO UPDATE
       SET role = GREATEST(note_collaborators.role, EXCLUDED.role), updated_at = now();
    RETURN true;
END
$$;
REVOKE ALL ON FUNCTION public.grant_note_collaborator(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.grant_note_collaborator(uuid, uuid) TO tenant_writer;

-- auth-service lets a note's authors (not only workspace managers) invite a
-- guest to that one note; it cannot read notes, so it asks here. Author team
-- of a live note in that tenant, or an owner/admin of the tenant.
CREATE FUNCTION public.can_manage_note(p_tenant uuid, p_note uuid, p_sub uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM notes n
         WHERE n.id = p_note AND n.tenant_id = p_tenant AND n.deleted_at IS NULL
           AND (n.primary_author_id = p_sub OR p_sub = ANY(n.co_author_ids)
                OR EXISTS (SELECT 1 FROM tenant_memberships m
                            WHERE m.tenant_id = p_tenant AND m.user_sub = p_sub
                              AND m.status = 'active' AND m.role IN ('owner', 'admin')))
    )
$$;
REVOKE ALL ON FUNCTION public.can_manage_note(uuid, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_manage_note(uuid, uuid, uuid) TO tenant_writer;
