-- 0077 — The workspace is the folder (W5). Four note columns and one table:
--
--   - `visibility_source`: who set the current visibility. `author` is a choice
--     no default, backfill or move may override; `backfill` marks the notes the
--     W5 script opened to the workspace, so their authors can review them.
--   - `media_state`: `rehoming` while a moved note's audio and transcript are
--     re-encrypted into the new workspace (transcript closed until `ready`);
--     `failed` when that job died (the note stays readable, the media does not).
--   - `copied_from_*`: provenance of a copy (no FK — the source may be in
--     another workspace, or gone).
--   - `note_relocations`: a stub in the SOURCE workspace saying where a moved
--     note went, and who had been able to see it here (only they are told).

ALTER TABLE notes
    ADD COLUMN visibility_source TEXT NOT NULL DEFAULT 'default'
        CHECK (visibility_source IN ('default', 'author', 'backfill')),
    ADD COLUMN media_state TEXT NOT NULL DEFAULT 'ready'
        CHECK (media_state IN ('ready', 'rehoming', 'failed')),
    ADD COLUMN copied_from_note_id   UUID,
    ADD COLUMN copied_from_tenant_id UUID;

-- The "review what changed" list (search `changed_by=backfill`).
CREATE INDEX notes_visibility_source_idx ON notes (tenant_id, primary_author_id)
    WHERE visibility_source = 'backfill';

CREATE TABLE note_relocations (
    note_id       UUID NOT NULL,                       -- no FK: the row outlives the note's presence here
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,   -- the SOURCE workspace
    to_tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    moved_by      UUID NOT NULL,
    moved_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    old_code      TEXT NOT NULL,
    new_code      TEXT NOT NULL,
    -- The audience the note had here: only these people are told where it went.
    was_workspace_visible BOOLEAN NOT NULL,
    author_team       UUID[] NOT NULL,
    collaborator_subs UUID[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant_id, note_id)
);
CREATE INDEX note_relocations_old_code_idx ON note_relocations (tenant_id, old_code);

ALTER TABLE note_relocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_relocations FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_relocations_tenant_select ON note_relocations
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_relocations_tenant_insert ON note_relocations
    FOR INSERT TO app_role
    WITH CHECK (false);  -- written only inside move_note_to_workspace (0078)
CREATE POLICY note_relocations_tenant_update ON note_relocations
    FOR UPDATE TO app_role
    USING (false);
CREATE POLICY note_relocations_tenant_delete ON note_relocations
    FOR DELETE TO app_role
    USING (false);
CREATE POLICY note_relocations_tenant_restrictive ON note_relocations
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT ON note_relocations TO app_role;
