-- 0072 — Workspace invitations (W2, ADR-0070). One entity for every case:
-- an address with or without an account, a workspace or (W3) one note.
-- Accepting is always an authenticated act by the invited address; the
-- token is hash-only at rest and only lets its holder *see* the invitation.
--
-- Same access pattern as `tenant_memberships`: auth-service reads and
-- writes across tenants through `tenant_writer`; `app_role` (note-service,
-- W3) may only SELECT the rows of the scoped tenant.

CREATE TABLE tenant_invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT NOT NULL CHECK (email = lower(email) AND char_length(email) <= 320),
    role            TEXT NOT NULL CHECK (role IN ('admin', 'member', 'viewer', 'guest')),
    note_id         UUID,                                    -- W3: per-note invitation; NULL = workspace
    note_role       TEXT CHECK (note_role IN ('view', 'comment', 'edit')),
    invited_by      UUID NOT NULL REFERENCES identities(id) ON DELETE RESTRICT,
    token_hash      BYTEA NOT NULL UNIQUE,
    message         TEXT NOT NULL DEFAULT '' CHECK (char_length(message) <= 500),
    lang            TEXT NOT NULL DEFAULT 'en' CHECK (lang IN ('en', 'de', 'uk')),
    expires_at      TIMESTAMPTZ NOT NULL,
    sent_count      INTEGER NOT NULL DEFAULT 0,
    last_sent_at    TIMESTAMPTZ,
    accepted_at     TIMESTAMPTZ,
    accepted_by     UUID REFERENCES identities(id) ON DELETE SET NULL,
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenant_invitations_note_role_chk CHECK ((note_id IS NULL) = (note_role IS NULL)),
    CONSTRAINT tenant_invitations_window CHECK (expires_at > created_at)
);

-- One live invitation per (workspace, address, note).
CREATE UNIQUE INDEX tenant_invitations_live_idx
    ON tenant_invitations (tenant_id, email, COALESCE(note_id, '00000000-0000-0000-0000-000000000000'))
    WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX tenant_invitations_email_idx ON tenant_invitations (email)
    WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX tenant_invitations_tenant_idx ON tenant_invitations (tenant_id, created_at DESC);

ALTER TABLE tenant_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_invitations FORCE ROW LEVEL SECURITY;
GRANT SELECT ON tenant_invitations TO app_role;           -- note-service (W3) lists a note's pending invites
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_invitations TO tenant_writer;
CREATE POLICY tenant_invitations_app_select ON tenant_invitations FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_invitations_writer_all ON tenant_invitations FOR ALL TO tenant_writer
    USING (true) WITH CHECK (true);
CREATE POLICY tenant_invitations_app_restrictive ON tenant_invitations AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- The workspace funnel (scripts/ops/workspace_funnel.sql, Grafana) reads counts
-- across tenants as funnel_reader (0040) — never the address or the message.
GRANT SELECT (id, tenant_id, role, note_id, invited_by, sent_count, created_at, expires_at,
              accepted_at, accepted_by, revoked_at)
    ON tenant_invitations TO funnel_reader;
CREATE POLICY funnel_reader_select ON tenant_invitations FOR SELECT TO funnel_reader USING (true);

COMMENT ON TABLE tenant_invitations IS
    'W2: invitations by e-mail; the address is PII (DSAR erase runbook), swept 90 days after it stops being live';

-- A row a person left keeps a timestamp so the roster can say "Left".
ALTER TABLE tenant_memberships ADD COLUMN left_at TIMESTAMPTZ;

-- The category CHECKs pinned in 0011 were never widened: four categories the
-- producers already emit (note.recipient_responded, note.link_status_changed,
-- share.reported, ai.budget_reached) would fail on insert. Widen to the full
-- `notification_events.Category` vocabulary, plus the three workspace ones.
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed'
    ));
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed'
    ));
