-- 0037 — Sprint 20: structured action items + recipient responses.
--
-- `note_action_items` is a DERIVED projection of a note version's
-- `action_items` section text, materialised when the note is finalized
-- or amended (domain/action_items.py). The section text stays canonical:
-- the version hash chain (ADR-0020/0024), the editor, PDF, Markdown and
-- search all keep working on prose, and nothing here can drift from it.
-- `item_key` is sha256 of the normalised line WITHOUT owner/date tokens,
-- so an unchanged line keeps its identity — and its responses — across
-- amendments, while an edited line starts clean (the recipient confirmed
-- THAT wording).
--
-- `share_link_responses` is what a recipient does on the shared page:
-- confirm / done / dispute an item, or flag a section as inaccurate.
-- The link is the recipient's identity (Sprint 19); there is no account.
-- One live row per (link, kind, target): changing one's mind replaces.
-- `comment` is text and only ever rendered as text — never Markdown,
-- never HTML, never in an e-mail.

CREATE TYPE action_item_status AS ENUM ('open', 'done', 'dropped');

CREATE TABLE note_action_items (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id           UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    note_version_id   UUID NOT NULL REFERENCES note_versions(id) ON DELETE RESTRICT,
    item_key          TEXT NOT NULL,
    position          INTEGER NOT NULL,
    text              TEXT NOT NULL CHECK (char_length(text) <= 500),
    owner_label       TEXT CHECK (owner_label IS NULL OR char_length(owner_label) <= 60),
    owner_confidence  REAL,
    due_date          DATE,
    due_text          TEXT CHECK (due_text IS NULL OR char_length(due_text) <= 120),
    due_confidence    REAL,
    status            action_item_status NOT NULL DEFAULT 'open',
    status_changed_by UUID,
    status_changed_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (note_version_id, item_key)
);
CREATE INDEX note_action_items_note_idx
    ON note_action_items (note_id, note_version_id, position);

ALTER TABLE note_action_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_action_items FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_action_items_tenant_select ON note_action_items
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_action_items_tenant_insert ON note_action_items
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_action_items_tenant_update ON note_action_items
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_action_items_tenant_delete ON note_action_items
    FOR DELETE TO app_role
    USING (false);  -- items are re-derived per version, never deleted
CREATE POLICY note_action_items_tenant_restrictive ON note_action_items
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON note_action_items TO app_role;

CREATE TYPE share_response_kind AS ENUM ('confirm', 'done', 'dispute', 'flag');

CREATE TABLE share_link_responses (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id      UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    link_id      UUID NOT NULL REFERENCES note_share_links(id) ON DELETE RESTRICT,
    kind         share_response_kind NOT NULL,
    item_key     TEXT,          -- confirm / done / dispute
    section_key  TEXT,          -- flag
    comment      TEXT CHECK (comment IS NULL OR char_length(comment) <= 280),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at   TIMESTAMPTZ,
    cleared_by   UUID,          -- NULL when the recipient withdrew it
    CHECK ((kind = 'flag' AND section_key IS NOT NULL AND item_key IS NULL)
        OR (kind <> 'flag' AND item_key IS NOT NULL AND section_key IS NULL))
);
CREATE UNIQUE INDEX share_link_responses_live_idx
    ON share_link_responses (link_id, kind, COALESCE(item_key, ''), COALESCE(section_key, ''))
    WHERE cleared_at IS NULL;
CREATE INDEX share_link_responses_note_idx
    ON share_link_responses (note_id, created_at DESC);

ALTER TABLE share_link_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE share_link_responses FORCE  ROW LEVEL SECURITY;
CREATE POLICY share_link_responses_tenant_select ON share_link_responses
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY share_link_responses_tenant_insert ON share_link_responses
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY share_link_responses_tenant_update ON share_link_responses
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY share_link_responses_tenant_delete ON share_link_responses
    FOR DELETE TO app_role
    USING (false);  -- clearing is the delete
CREATE POLICY share_link_responses_tenant_restrictive ON share_link_responses
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON share_link_responses TO app_role;
