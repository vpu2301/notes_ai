-- 0008 — `templates`: the note-template content surface.
--
-- One row per (tenant, code, schema_version) pair. tenant_id IS NULL
-- denotes a SYSTEM template (visible to all tenants; managed via the
-- seed path only). A tenant clones a system template by INSERTing a
-- row with `parent_template_id` set and `tenant_id` = its own.
--
-- Versioning (ADR-0016):
--   - Cosmetic edit (name / aliases / asr_prompt / order / default_content /
--     metadata): UPDATE in place; schema_version bumps.
--   - Structural edit (section added/removed/field_type-changed/
--     required-flipped/min_chars-tightened): INSERT new row with
--     parent_template_id set + schema_version reset to 1.
--
-- Lifecycle:
--   draft → active → deprecated. No hard delete (notes reference
--   templates by id; references must outlive deprecation).
--
-- `category` is the coarse browse facet ("meetings", "sales", "hr",
-- "projects", …) mirrored from schema_jsonb for index efficiency.

CREATE TABLE templates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID REFERENCES tenants(id),         -- NULL = system
    parent_template_id  UUID REFERENCES templates(id),       -- structural-edit lineage
    code                TEXT NOT NULL,                       -- "meeting_notes"
    name                TEXT NOT NULL,
    language            TEXT NOT NULL CHECK (language IN ('uk','en')),
    category            TEXT NOT NULL,
    schema_version      SMALLINT NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
    is_system           BOOLEAN NOT NULL DEFAULT FALSE,
    status              TEXT NOT NULL CHECK (status IN ('draft','active','deprecated'))
                            DEFAULT 'draft',
    schema_jsonb        JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT so system rows (tenant_id NULL) also conflict:
    -- with the default NULLS DISTINCT semantics the ON CONFLICT in
    -- upsert_system_template() would never fire for system templates and
    -- every re-seed would duplicate them.
    UNIQUE NULLS NOT DISTINCT (tenant_id, code, schema_version)
);

CREATE INDEX idx_templates_tenant_category
    ON templates (tenant_id, category, language)
    WHERE status <> 'deprecated';
CREATE INDEX idx_templates_system_category
    ON templates (category, language)
    WHERE tenant_id IS NULL AND status <> 'deprecated';
CREATE INDEX idx_templates_parent
    ON templates (parent_template_id)
    WHERE parent_template_id IS NOT NULL;

CREATE TRIGGER templates_set_updated_at
    BEFORE UPDATE ON templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Grants ───────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON templates TO app_role;
-- System rows (tenant_id IS NULL) are inserted only by tenant_writer via
-- the seed path. app_role's policies below enforce this.
GRANT SELECT, INSERT, UPDATE ON templates TO tenant_writer;

-- ── Row-level security ──────────────────────────────────────────────
ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE templates FORCE  ROW LEVEL SECURITY;

-- Visibility: own-tenant rows OR system rows (tenant_id IS NULL).
CREATE POLICY templates_visibility ON templates
    FOR SELECT TO app_role
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR tenant_id IS NULL
    );

-- Writes (INSERT/UPDATE) — restrict to own-tenant rows only. A tenant
-- can never insert a row with tenant_id = NULL (system) or another
-- tenant's UUID.
CREATE POLICY templates_write ON templates
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY templates_update ON templates
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY templates_restrictive ON templates
    AS RESTRICTIVE FOR SELECT
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR tenant_id IS NULL
    );

-- tenant_writer (seed role) has unrestricted access to write system rows.
CREATE POLICY templates_tenant_writer_all ON templates
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);

-- Hard-delete prevention: DELETE is not granted; only soft-delete via
-- UPDATE status='deprecated'. Notes reference templates with
-- ON DELETE RESTRICT (0009).
REVOKE DELETE ON templates FROM app_role, tenant_writer;

-- ── System-template upsert helper ───────────────────────────────────
-- Called by scripts/seed/seed.py, which reads the JSON files in
-- infra/seeds/templates/ (reviewable in PRs) and upserts each one.
-- Keeping the function in the migration ensures fresh DBs can run the
-- seeds the same way. Idempotent on (tenant_id, code, schema_version);
-- on conflict cosmetic fields are updated (structural changes require a
-- new schema_version).

CREATE OR REPLACE FUNCTION upsert_system_template(
    p_code           TEXT,
    p_name           TEXT,
    p_language       TEXT,
    p_category       TEXT,
    p_schema_version SMALLINT,
    p_schema_jsonb   JSONB
) RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO templates
        (tenant_id, parent_template_id, code, name, language, category,
         schema_version, is_system, status, schema_jsonb)
    VALUES
        (NULL, NULL, p_code, p_name, p_language, p_category,
         p_schema_version, TRUE, 'active', p_schema_jsonb)
    ON CONFLICT (tenant_id, code, schema_version) DO UPDATE
        SET name = EXCLUDED.name,
            category = EXCLUDED.category,
            schema_jsonb = EXCLUDED.schema_jsonb,
            updated_at = now()
    RETURNING id INTO v_id;
    RETURN v_id;
END;
$$;
