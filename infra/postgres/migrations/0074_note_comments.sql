-- 0074 — Comments on a note (W3 B-4, ADR-0071). Anyone at `comment` level or
-- above writes them; anchored to the whole note, a section (`section_key`) or
-- an action item (`item_key`). Bodies are content: they cascade with the note,
-- belong in a DSAR export, and are never logged or put in a notification.
-- Delete is soft (`deleted_at`); hard DELETE is forbidden by policy.

CREATE TABLE note_comments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id      UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    author_sub   UUID NOT NULL,
    anchor_kind  TEXT NOT NULL CHECK (anchor_kind IN ('note', 'section', 'item')),
    anchor_key   TEXT NOT NULL DEFAULT '' CHECK (char_length(anchor_key) <= 200),
    body         TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    edited_at    TIMESTAMPTZ,
    resolved_at  TIMESTAMPTZ,
    resolved_by  UUID,
    deleted_at   TIMESTAMPTZ,
    deleted_by   UUID
);

CREATE INDEX note_comments_note_idx
    ON note_comments (note_id, created_at)
    WHERE deleted_at IS NULL;

ALTER TABLE note_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_comments FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_comments_tenant_select ON note_comments
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_comments_tenant_insert ON note_comments
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_comments_tenant_update ON note_comments
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_comments_tenant_delete ON note_comments
    FOR DELETE TO app_role
    USING (false);  -- deleted_at is the delete

CREATE POLICY note_comments_tenant_restrictive ON note_comments
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON note_comments TO app_role;

COMMENT ON TABLE note_comments IS
    'W3: comments on a note; body is content (DSAR export, cascade on note delete, never logged)';

-- Two note categories (B-10): a comment, and a change to someone's role on a note.
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed'
    ));
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed'
    ));
