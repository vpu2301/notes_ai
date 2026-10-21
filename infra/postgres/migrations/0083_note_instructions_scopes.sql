-- 0083 — Sprint N4: a text per meeting type that extends the workspace text, and a text for
-- one note. The order calls this 0081; 0081 (N5's dashboard grant) and 0082 (N0) came first.
-- A type row is compiled together with the workspace text and records the workspace
-- version it was built on (`base_versions`); a workspace change marks every type row
-- `stale` until the recompile job has run. A note row is a one-off, never recompiled.
-- The text is content: never logged.

ALTER TABLE workspace_note_instructions
    DROP CONSTRAINT workspace_note_instructions_scope_check,
    ADD CONSTRAINT workspace_note_instructions_scope_check CHECK (scope IN
        ('workspace', 'client', 'team', 'sales', 'one_on_one', 'interview', 'broadcast', 'memo')),
    DROP CONSTRAINT workspace_note_instructions_compile_status_check,
    ADD CONSTRAINT workspace_note_instructions_compile_status_check
        CHECK (compile_status IN ('compiled', 'failed', 'stale')),
    ADD COLUMN base_versions JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(base_versions) = 'object');

CREATE TABLE note_instructions (
    tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    note_id            UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    text               TEXT NOT NULL CHECK (char_length(text) BETWEEN 1 AND 8000),
    profile            JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(profile) = 'object'),
    profile_hash       TEXT NOT NULL,
    compile_status     TEXT NOT NULL CHECK (compile_status IN ('compiled', 'failed')),
    compile_error_kind TEXT CHECK (
        compile_error_kind IS NULL
        OR compile_error_kind IN ('provider_error', 'invalid_output', 'timeout', 'budget_exceeded')
    ),
    compiler_version   TEXT NOT NULL,
    base_versions      JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(base_versions) = 'object'),
    updated_by         UUID NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id)
);
CREATE INDEX note_instructions_tenant_idx ON note_instructions (tenant_id);

CREATE TRIGGER note_instructions_set_updated_at
    BEFORE UPDATE ON note_instructions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Editors read and write through the routes (access.require_edit); the app deletes rows.
ALTER TABLE note_instructions ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_instructions FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_instructions_tenant_select ON note_instructions
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_instructions_tenant_insert ON note_instructions
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_instructions_tenant_update ON note_instructions
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_instructions_tenant_delete ON note_instructions
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_instructions_tenant_restrictive ON note_instructions
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON note_instructions TO app_role;
