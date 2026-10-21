-- Note instructions (Sprint N1): a workspace's plain-text instructions for how its notes
-- are written, and the writing profile compiled from them. The text is configuration
-- treated as content: never logged. One row per (tenant, scope); no row = write as today.

CREATE TABLE workspace_note_instructions (
    tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    scope              TEXT NOT NULL DEFAULT 'workspace' CHECK (scope IN ('workspace')),
    version            INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    text               TEXT NOT NULL CHECK (char_length(text) BETWEEN 1 AND 8000),
    profile            JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(profile) = 'object'),
    profile_hash       TEXT NOT NULL,
    compile_status     TEXT NOT NULL CHECK (compile_status IN ('compiled', 'failed')),
    compile_error_kind TEXT CHECK (
        compile_error_kind IS NULL
        OR compile_error_kind IN ('provider_error', 'invalid_output', 'timeout', 'budget_exceeded')
    ),
    compiler_version   TEXT NOT NULL,
    backend            TEXT,
    updated_by         UUID NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope)
);

CREATE TRIGGER workspace_note_instructions_set_updated_at
    BEFORE UPDATE ON workspace_note_instructions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Every member may read; the route lets only an admin write. The app deletes rows
-- (an emptied text), so DELETE is allowed for the tenant's own row.
ALTER TABLE workspace_note_instructions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_note_instructions FORCE  ROW LEVEL SECURITY;
CREATE POLICY workspace_note_instructions_tenant_select ON workspace_note_instructions
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_note_instructions_tenant_insert ON workspace_note_instructions
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_note_instructions_tenant_update ON workspace_note_instructions
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_note_instructions_tenant_delete ON workspace_note_instructions
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_note_instructions_tenant_restrictive ON workspace_note_instructions
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_note_instructions TO app_role;
