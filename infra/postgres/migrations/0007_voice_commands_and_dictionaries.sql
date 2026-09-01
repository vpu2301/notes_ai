-- 0007 — dictation-time vocabulary tables:
--   * voice_commands            — global spoken-command catalogue
--   * abbreviation_dictionary   — global + per-tenant abbreviation rules
--   * synonyms                  — search-time query-expansion dictionary

-- ── voice_commands ──────────────────────────────────────────────────
-- Global (not tenant-scoped). The matcher's vocabulary is loaded from
-- this table on nlp-service startup; updates land via DB seed (data,
-- not code — see scripts/seed/seed.py + infra/postgres/seed/*.json).

CREATE TABLE voice_commands (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent                   TEXT NOT NULL,
    language                 TEXT NOT NULL CHECK (language IN ('uk','en','de')),
    phrases                  JSONB NOT NULL,                    -- list of word-lists
    requires_pause_before_ms INTEGER NOT NULL DEFAULT 200,
    min_avg_probability      REAL NOT NULL DEFAULT 0.85,
    is_section_command       BOOLEAN NOT NULL DEFAULT FALSE,
    -- Marks commands the FSM only honours while a choice-capture flow is
    -- armed (choice.set / choice.add / choice.remove); outside that flow
    -- their words pass through as plain dictated text.
    is_option_command        BOOLEAN NOT NULL DEFAULT FALSE,
    -- Refuses prefix/fuzzy matching for commands whose words often occur
    -- verbatim inside normal prose.
    exact_match_only         BOOLEAN NOT NULL DEFAULT FALSE,
    is_active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX voice_commands_language_active_idx
    ON voice_commands (language, is_active);

-- Public catalogue; both app_role and audit_reader read it.
GRANT SELECT ON voice_commands TO app_role, audit_reader;
GRANT INSERT, UPDATE, DELETE ON voice_commands TO tenant_writer;
-- No RLS: the catalogue is global (documented exemption in
-- scripts/ci/check-rls-policies.py). Per-tenant overrides are future scope.

-- ── abbreviation_dictionary ─────────────────────────────────────────
-- ``tenant_id IS NULL`` → global rule (DBA / seed-managed).
-- ``tenant_id IS NOT NULL`` → tenant override; wins on collision.
--
-- The snapshot pattern reads merged rules ONCE at NLP request entry;
-- admin edits don't affect in-flight processing.

CREATE TABLE abbreviation_dictionary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id),
    language        TEXT NOT NULL CHECK (language IN ('uk','en','de')),
    expanded        TEXT NOT NULL,
    abbreviated     TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('expand','compact','either')),
    domain          TEXT,                                  -- e.g. 'all', 'sales', NULL
    case_sensitive  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, language, expanded, abbreviated)
);

CREATE INDEX abbrev_tenant_language_idx
    ON abbreviation_dictionary (tenant_id, language);
CREATE INDEX abbrev_global_language_idx
    ON abbreviation_dictionary (language)
    WHERE tenant_id IS NULL;

CREATE TRIGGER abbreviation_dictionary_set_updated_at
    BEFORE UPDATE ON abbreviation_dictionary
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON abbreviation_dictionary TO app_role;
-- tenant_writer owns inserts of global rules via seed.
GRANT INSERT, UPDATE, DELETE ON abbreviation_dictionary TO tenant_writer;

ALTER TABLE abbreviation_dictionary ENABLE ROW LEVEL SECURITY;
ALTER TABLE abbreviation_dictionary FORCE  ROW LEVEL SECURITY;

-- Read: own tenant rows OR global rows.
CREATE POLICY abbreviation_dictionary_read ON abbreviation_dictionary
    FOR SELECT TO app_role
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR tenant_id IS NULL
    );

-- Write: only OWN tenant rows. Global rows are immutable through the
-- app role; seeds use the tenant_writer role.
CREATE POLICY abbreviation_dictionary_write_own ON abbreviation_dictionary
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY abbreviation_dictionary_update_own ON abbreviation_dictionary
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY abbreviation_dictionary_delete_own ON abbreviation_dictionary
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- RESTRICTIVE defence in depth: a future PERMISSIVE policy can't
-- accidentally expose another tenant's rows.
CREATE POLICY abbreviation_dictionary_restrictive ON abbreviation_dictionary
    AS RESTRICTIVE FOR SELECT
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR tenant_id IS NULL
    );

-- ── synonyms ────────────────────────────────────────────────────────
-- Query-expansion dictionary for note search. `simple` FTS has no
-- stemming and no synonyms; rows group equivalent terms under one
-- group_id and search expands a matched query lexeme to
-- (term OR syn1 OR syn2) tsquery groups.
--
-- Two scopes (the autocomplete_phrases model, minus the user tier):
--   system → tenant_id NULL  (seeded, visible to every tenant, immutable
--                             to app_role; tenant_writer curates)
--   tenant → tenant_id set   (tenant_admin-curated via /v1/synonyms)
--
-- `lexemes` is the term pre-normalized through to_tsvector('simple', …)
-- AT WRITE TIME — query-time matching is a plain array-overlap (&&) on
-- the GIN index, and both sides are guaranteed the same normalization
-- because both run through the same Postgres config. NB this is
-- deliberately NOT the nlp-service `abbreviation_dictionary`: that one
-- rewrites TRANSCRIPT text at dictation time (direction-aware,
-- replay-deterministic); this one broadens SEARCH recall at query time
-- and is tenant-extendable.
--
-- RLS lessons paid for by earlier iterations: at least one PERMISSIVE
-- policy per command (restrictive-only = deny-all), nil-uuid coalesce in
-- the unique index, and `tenant_writer` already exists (never CREATE
-- ROLE it here).

CREATE TABLE synonyms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    group_id    UUID NOT NULL,
    term        TEXT NOT NULL CHECK (length(btrim(term)) BETWEEN 1 AND 120),
    lexemes     TEXT[] NOT NULL CHECK (cardinality(lexemes) >= 1),
    language    TEXT NOT NULL CHECK (language IN ('uk', 'en')),
    source      TEXT NOT NULL CHECK (source IN ('system', 'tenant')),
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT synonym_scope_shape CHECK (
        (source = 'system' AND tenant_id IS NULL)
     OR (source = 'tenant' AND tenant_id IS NOT NULL)
    )
);

-- Term unique within its group per scope (nil-uuid idiom). The same term
-- MAY appear in two groups — expansion unions the alternatives.
CREATE UNIQUE INDEX synonyms_unique_term_per_group
    ON synonyms (
        coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
        group_id,
        lower(term),
        language
    );

-- Query-time lookup: WHERE lexemes && ARRAY[<query lexemes>].
CREATE INDEX synonyms_lexemes_gin ON synonyms USING gin (lexemes);
CREATE INDEX synonyms_group_idx ON synonyms (group_id);

ALTER TABLE synonyms ENABLE ROW LEVEL SECURITY;
ALTER TABLE synonyms FORCE ROW LEVEL SECURITY;

-- PERMISSIVE visibility: system rows for everyone, tenant rows for the
-- owning tenant.
CREATE POLICY synonyms_visibility ON synonyms
    FOR SELECT TO app_role
    USING (
        source = 'system'
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );

-- PERMISSIVE writes: app_role touches ONLY tenant-scope rows of its own
-- tenant (the synonym.write permission narrows this to tenant_admin at
-- the app layer). System rows are unreachable for every write command —
-- there is no PERMISSIVE policy granting them, which IS the guard.
CREATE POLICY synonyms_tenant_insert ON synonyms
    FOR INSERT TO app_role
    WITH CHECK (
        source = 'tenant'
        AND tenant_id = current_setting('app.tenant_id', true)::uuid
    );
CREATE POLICY synonyms_tenant_update ON synonyms
    FOR UPDATE TO app_role
    USING (source = 'tenant' AND tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (source = 'tenant' AND tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY synonyms_tenant_delete ON synonyms
    FOR DELETE TO app_role
    USING (source = 'tenant' AND tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON synonyms TO app_role;

-- Seed/curation role for system rows.
GRANT SELECT, INSERT, UPDATE, DELETE ON synonyms TO tenant_writer;
CREATE POLICY synonyms_seed_select ON synonyms
    FOR SELECT TO tenant_writer USING (true);
CREATE POLICY synonyms_seed_insert ON synonyms
    FOR INSERT TO tenant_writer WITH CHECK (source = 'system');
CREATE POLICY synonyms_seed_update ON synonyms
    FOR UPDATE TO tenant_writer USING (source = 'system') WITH CHECK (source = 'system');
CREATE POLICY synonyms_seed_delete ON synonyms
    FOR DELETE TO tenant_writer USING (source = 'system');
