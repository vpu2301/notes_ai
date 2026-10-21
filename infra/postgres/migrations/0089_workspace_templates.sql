-- 0089 — Sprint P2: a workspace's own text for a built-in note template (overrides the
-- file of the same name and language), and the template a note is written with.
-- The Markdown is configuration treated as content: never logged.

CREATE TABLE workspace_templates (
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (name IN (
                    'meeting', 'client_call', 'interview', 'broadcast', 'public_meeting', 'memo', 'auto'
                )),
    language    TEXT NOT NULL CHECK (language IN ('en', 'de', 'uk')),
    markdown    TEXT NOT NULL CHECK (char_length(markdown) BETWEEN 1 AND 4000),
    updated_by  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name, language)
);

CREATE TRIGGER workspace_templates_set_updated_at
    BEFORE UPDATE ON workspace_templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE workspace_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_templates FORCE  ROW LEVEL SECURITY;
CREATE POLICY workspace_templates_tenant_select ON workspace_templates
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_templates_tenant_insert ON workspace_templates
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_templates_tenant_update ON workspace_templates
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_templates_tenant_delete ON workspace_templates
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_templates_tenant_restrictive ON workspace_templates
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_templates TO app_role;

-- The template a note is written with; NULL = `auto` (the model chooses).
ALTER TABLE notes
    ADD COLUMN template TEXT
        CHECK (template IS NULL OR template IN (
            'meeting', 'client_call', 'interview', 'broadcast', 'public_meeting', 'memo', 'auto'
        ));
