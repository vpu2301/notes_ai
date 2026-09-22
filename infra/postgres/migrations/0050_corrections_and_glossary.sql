-- 0050 — Sprint 35: what the author fixes, and what the workspace learns.
--
-- Two tables, one idea: a correction is worth keeping, and the same
-- correction should not be needed twice.
--
-- `note_item_corrections` is the LOG of author corrections to generated
-- lines — dismissed, restored, owner or date changed. It holds NO free
-- text and no item text: only the line's `item_key` (a truncated sha256),
-- the kind, a closed-vocabulary reason and the flags that were on the
-- line at the time. That is deliberate — the table feeds the weekly
-- quality report and the eval gold set, both of which must be readable by
-- a reporting role that may never see note content.
--
-- `workspace_glossary` is the names, companies, products and terms this
-- workspace spells a particular way, with the ways they have been
-- misheard. It is used three ways: as the capture form's vocabulary hint
-- so ASR hears them next time, in the generation prompt so the model
-- spells them right, and to canonicalise an owner. Terms ARE personal and
-- business data: tenant-scoped, in the DSAR export, gone with the tenant,
-- never in a log or an audit payload.

CREATE TABLE note_item_corrections (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id        UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    item_key       TEXT NOT NULL CHECK (char_length(item_key) <= 64),
    -- The item's kind when it was corrected ('action', 'decision', …).
    kind           TEXT NOT NULL CHECK (char_length(kind) <= 32),
    action         TEXT NOT NULL
        CHECK (action IN ('dismiss','restore','add','owner_changed','due_changed','kind_changed')),
    reason         TEXT
        CHECK (reason IN ('not_said','not_a_decision','not_a_task','wrong_owner',
                          'wrong_date','duplicate','not_relevant')),
    -- The flags the line carried when the author disagreed with it: the
    -- signal for "do flags predict errors" (hypothesis V3).
    flags_at_time  TEXT[] NOT NULL DEFAULT '{}',
    prompt_version TEXT CHECK (prompt_version IS NULL OR char_length(prompt_version) <= 64),
    model_id       TEXT CHECK (model_id IS NULL OR char_length(model_id) <= 128),
    actor_sub      UUID NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX note_item_corrections_note_idx
    ON note_item_corrections (note_id, item_key, created_at DESC);
-- The weekly report reads by tenant and week.
CREATE INDEX note_item_corrections_week_idx
    ON note_item_corrections (tenant_id, created_at);

ALTER TABLE note_item_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_item_corrections FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_item_corrections_tenant_select ON note_item_corrections
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_item_corrections_tenant_insert ON note_item_corrections
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- A correction log that can be rewritten is not a log.
CREATE POLICY note_item_corrections_tenant_update ON note_item_corrections
    FOR UPDATE TO app_role USING (false);
CREATE POLICY note_item_corrections_tenant_delete ON note_item_corrections
    FOR DELETE TO app_role USING (false);
CREATE POLICY note_item_corrections_tenant_restrictive ON note_item_corrections
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON note_item_corrections TO app_role;


CREATE TABLE workspace_glossary (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    term        TEXT NOT NULL CHECK (char_length(term) BETWEEN 2 AND 80),
    kind        TEXT NOT NULL CHECK (kind IN ('person','company','product','term')),
    -- How it has been misheard or misspelled; ≤ 8, each ≤ 80 characters.
    heard_as    TEXT[] NOT NULL DEFAULT '{}'
        CHECK (array_length(heard_as, 1) IS NULL OR array_length(heard_as, 1) <= 8),
    created_by  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);
-- One live row per spelling per workspace; a deleted term may be re-added.
CREATE UNIQUE INDEX workspace_glossary_term_uq
    ON workspace_glossary (tenant_id, lower(term))
    WHERE deleted_at IS NULL;
CREATE INDEX workspace_glossary_live_idx
    ON workspace_glossary (tenant_id, kind) WHERE deleted_at IS NULL;

ALTER TABLE workspace_glossary ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_glossary FORCE  ROW LEVEL SECURITY;
CREATE POLICY workspace_glossary_tenant_select ON workspace_glossary
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_glossary_tenant_insert ON workspace_glossary
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Delete is a soft delete, so it is an UPDATE.
CREATE POLICY workspace_glossary_tenant_update ON workspace_glossary
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY workspace_glossary_tenant_delete ON workspace_glossary
    FOR DELETE TO app_role USING (false);
CREATE POLICY workspace_glossary_tenant_restrictive ON workspace_glossary
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON workspace_glossary TO app_role;
