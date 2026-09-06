-- 0021 — Spaces: personal folders for notes, shared across a user's devices.
--
-- The Mac app had "spaces" as local folders in UserDefaults; the phone
-- app could not see them, and neither could the web app. So a space is a
-- server row now: a user's own list of named folders, plus which of the
-- notes they can see is filed where. Spaces are personal (scoped to
-- ``user_sub`` on top of tenant RLS) — a colleague sees the same notes,
-- but files them their own way.
--
-- A note is in at most ONE space per user (``note_space_items`` has one
-- row per user × note; ``space_id`` NULL = "not filed", which is also
-- what unfiling writes). Deleting a space stamps ``deleted_at`` and
-- unfiles its notes; hard DELETE is forbidden by policy, as everywhere.

CREATE TABLE note_spaces (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_sub    UUID NOT NULL,
    name        TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE INDEX note_spaces_user_idx
    ON note_spaces (tenant_id, user_sub, created_at)
    WHERE deleted_at IS NULL;

ALTER TABLE note_spaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_spaces FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_spaces_tenant_select ON note_spaces
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_spaces_tenant_insert ON note_spaces
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_spaces_tenant_update ON note_spaces
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_spaces_tenant_delete ON note_spaces
    FOR DELETE TO app_role
    USING (false);  -- deleted_at is the delete

CREATE POLICY note_spaces_tenant_restrictive ON note_spaces
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON note_spaces TO app_role;


CREATE TABLE note_space_items (
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_sub    UUID NOT NULL,
    note_id     UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    -- NULL = not filed anywhere (unfiled rather than deleted).
    space_id    UUID REFERENCES note_spaces(id) ON DELETE RESTRICT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_sub, note_id)
);

CREATE INDEX note_space_items_space_idx
    ON note_space_items (space_id)
    WHERE space_id IS NOT NULL;

ALTER TABLE note_space_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_space_items FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_space_items_tenant_select ON note_space_items
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_space_items_tenant_insert ON note_space_items
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_space_items_tenant_update ON note_space_items
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_space_items_tenant_delete ON note_space_items
    FOR DELETE TO app_role
    USING (false);  -- unfiling (space_id = NULL) is the delete

CREATE POLICY note_space_items_tenant_restrictive ON note_space_items
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON note_space_items TO app_role;
