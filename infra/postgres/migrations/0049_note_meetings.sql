-- 0049 — Sprint 34: the note exists from the first second.
--
-- Pressing Record now creates the note (POST /v1/notes/meeting) instead of
-- waiting for a transcript. The capture's LIFECYCLE lives here, on a
-- sidecar, and not on `notes.status`: ADR-0051 retired every status but
-- draft/cancelled, and "is the audio still uploading" is not a property of
-- the document. `notes.source_asr_job_id` becomes set-once-LATER — the
-- partial unique index from 0045 still guarantees one note per job.
--
-- `note_user_line_times` is when the author first typed each line of the
-- `user_notes` section, relative to `started_at`. It is a sidecar for the
-- same reason: `NoteContent` is extra="forbid" and hash-chained (ADR-0020),
-- and typing rhythm is not part of the record. `line_key` is
-- action_items.item_key(normalise_text(line)) — a truncated sha256, so
-- nothing here is content.
--
-- `calendar_context` holds attendee names and invite agenda lines. Those
-- ARE content: tenant-scoped, never logged or audited (pii_filter), gone
-- with the note.

CREATE TABLE note_meetings (
    note_id           UUID PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    created_by        UUID NOT NULL,
    state             TEXT NOT NULL
        CHECK (state IN ('recording','uploading','transcribing','generating',
                         'ready','no_audio','failed')),
    -- Idempotency across retries, double taps and a second device.
    client_capture_id UUID NOT NULL,
    asr_job_id        UUID,
    meeting_type      TEXT NOT NULL DEFAULT 'auto'
        CHECK (meeting_type IN ('auto','client','team','sales','one_on_one','interview')),
    -- The client's clock at record start; recording t=0 for line offsets.
    started_at        TIMESTAMPTZ NOT NULL,
    -- {source, title, ical_uid, attendee_names[<=12], agenda_lines[<=20]}
    calendar_context  JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(calendar_context) = 'object'),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, client_capture_id)
);
-- The sweeper's scan and the "finish what the closed laptop started" read.
CREATE INDEX note_meetings_state_idx ON note_meetings (tenant_id, state, updated_at);

CREATE TRIGGER note_meetings_set_updated_at
    BEFORE UPDATE ON note_meetings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE note_user_line_times (
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id    UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    line_key   TEXT NOT NULL CHECK (char_length(line_key) <= 64),
    -- First keystroke of the line, relative to note_meetings.started_at.
    offset_ms  INTEGER NOT NULL CHECK (offset_ms >= 0),
    PRIMARY KEY (note_id, line_key)
);

-- ── Row-level security (the 0037 shape) ─────────────────────────────
ALTER TABLE note_meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_meetings FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_meetings_tenant_select ON note_meetings
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_meetings_tenant_insert ON note_meetings
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_meetings_tenant_update ON note_meetings
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_meetings_tenant_delete ON note_meetings
    FOR DELETE TO app_role
    USING (false);  -- a capture's history is never rewritten; the note cascades
CREATE POLICY note_meetings_tenant_restrictive ON note_meetings
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON note_meetings TO app_role;

ALTER TABLE note_user_line_times ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_user_line_times FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_user_line_times_tenant_select ON note_user_line_times
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_user_line_times_tenant_insert ON note_user_line_times
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_user_line_times_tenant_update ON note_user_line_times
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Deleted, unlike meetings: a line the author removed while recording
-- leaves no timing behind.
CREATE POLICY note_user_line_times_tenant_delete ON note_user_line_times
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_user_line_times_tenant_restrictive ON note_user_line_times
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON note_user_line_times TO app_role;
