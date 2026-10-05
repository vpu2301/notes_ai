-- 0051 — Sprint 36: meetings come in series.
--
-- The most useful line in a weekly client call is "still open from last
-- week", and until now notes had no edge to each other: `notes` knew only
-- which dictation session or transcription job it came from.
--
-- `series_key` is a HASH, never content. Its preferred source is the
-- calendar event's iCalendar UID, which every instance of a recurring
-- event shares and which Sprint 34 already stores in
-- `note_meetings.calendar_context`. A one-off event has a unique UID, so
-- it simply never finds a previous note — the right outcome, reached
-- without a special case.
--
-- `note_carried_items` is the previous meeting's open items, restated in
-- the new one. They keep the PREVIOUS note's `item_key`, so a recipient's
-- confirmation and (when Sprint 33 lands) the evidence behind the item
-- stay reachable from the meeting where it was agreed.
--
-- Binding visibility rule (ADR-0057): carry-over reads another note only
-- when the author of the NEW note may view it. Enforced in
-- `domain/access.py` at the point of use, not here — RLS scopes to the
-- tenant, and "my colleague's private note" is inside my tenant.

ALTER TABLE note_meetings
    ADD COLUMN series_key       TEXT CHECK (series_key IS NULL OR char_length(series_key) <= 64),
    ADD COLUMN series_source    TEXT
        CHECK (series_source IS NULL OR series_source IN ('calendar_uid','title_attendees','manual')),
    ADD COLUMN previous_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    -- What detection thought this meeting was, and how it decided. The
    -- note's template is NOT switched on the strength of it: switching
    -- rewrites the document's skeleton under the author.
    ADD COLUMN meeting_type_detected TEXT
        CHECK (meeting_type_detected IS NULL OR meeting_type_detected IN
               ('auto','client','team','sales','one_on_one','interview')),
    ADD COLUMN detected_by TEXT
        CHECK (detected_by IS NULL OR detected_by IN ('keywords','model','user'));

-- "The previous meeting in this series": newest first, within a tenant.
CREATE INDEX note_meetings_series_idx
    ON note_meetings (tenant_id, series_key, started_at DESC)
    WHERE series_key IS NOT NULL;

CREATE TABLE note_carried_items (
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    -- The NEW meeting's note.
    note_id       UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    from_note_id  UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    -- The item's key in the PREVIOUS note, which is what keeps its
    -- responses and its evidence reachable.
    item_key      TEXT NOT NULL CHECK (char_length(item_key) <= 64),
    position      INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL
        CHECK (state IN ('open','done_mentioned','done_marked','dropped')),
    -- Only for `done_mentioned`: the words that say it was done, and
    -- where in the recording they are. Content — never logged.
    done_quote    TEXT CHECK (done_quote IS NULL OR char_length(done_quote) <= 500),
    done_start_ms INTEGER CHECK (done_start_ms IS NULL OR done_start_ms >= 0),
    done_end_ms   INTEGER CHECK (done_end_ms IS NULL OR done_end_ms >= 0),
    done_speaker  TEXT CHECK (done_speaker IS NULL OR char_length(done_speaker) <= 80),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, from_note_id, item_key)
);
CREATE INDEX note_carried_items_note_idx ON note_carried_items (note_id, position);

CREATE TRIGGER note_carried_items_set_updated_at
    BEFORE UPDATE ON note_carried_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Row-level security (the 0037 shape) ─────────────────────────────
ALTER TABLE note_carried_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_carried_items FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_carried_items_tenant_select ON note_carried_items
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_carried_items_tenant_insert ON note_carried_items
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_carried_items_tenant_update ON note_carried_items
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Dropping a carried item is a state, not a delete: "the author decided
-- this is no longer open" is worth keeping.
CREATE POLICY note_carried_items_tenant_delete ON note_carried_items
    FOR DELETE TO app_role USING (false);
CREATE POLICY note_carried_items_tenant_restrictive ON note_carried_items
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON note_carried_items TO app_role;
