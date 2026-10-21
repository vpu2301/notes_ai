-- 0079 — Versioned prompt/model profiles and experiments (S3).
--
-- A workspace may write its notes with its own stage instructions and model
-- settings, tested before it is used. Four rules the tables enforce, not
-- only the routes:
--
--   * A saved version never changes: app_role may INSERT and SELECT
--     versions, never UPDATE them (and a trigger refuses it for anyone).
--     Editing saves a new version.
--   * One pointer per workspace says which version writes its notes
--     (`prompt_profile_bindings`). Moving it bumps `revision`; a writer that
--     expected another revision loses (the route's 409). No pointer = the
--     profile bundled with the code.
--   * Every id is tenant-scoped across foreign keys: a version, a binding,
--     an experiment or a run can only point at its own workspace's rows.
--   * An experiment never writes a note. Its results live in its own
--     tables and the object store, under the source's access rules.
--
-- `note_generations.config_snapshot` pins what a queued generation will run
-- with (profile version, prompt hashes, flags, language, models), so a
-- settings change never alters a queued or running job.

CREATE TABLE prompt_profiles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name         TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    description  TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
    created_by   UUID NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id)
);

CREATE TABLE prompt_profile_versions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL,
    profile_id         UUID NOT NULL,
    version_number     INTEGER NOT NULL CHECK (version_number >= 1),
    -- {stages: {extraction|composition|verification: text|null},
    --  models: {stage: backend|null}, params: {stage: {...}},
    --  output_language: "auto"|code, length: short|standard|detailed}
    config             JSONB NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    -- What the instructions were written against; a rollback to a version whose
    -- contract or algorithm the code no longer runs is refused.
    contract_version   TEXT NOT NULL,
    schema_version     TEXT NOT NULL,
    algorithm_version  TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    created_by         UUID NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, profile_id, version_number),
    FOREIGN KEY (tenant_id, profile_id) REFERENCES prompt_profiles (tenant_id, id) ON DELETE CASCADE
);

CREATE FUNCTION prompt_profile_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'prompt profile versions are immutable; save a new version';
END;
$$;
CREATE TRIGGER prompt_profile_versions_no_update
    BEFORE UPDATE ON prompt_profile_versions
    FOR EACH ROW EXECUTE FUNCTION prompt_profile_versions_immutable();

CREATE TABLE prompt_profile_bindings (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    -- NULL = the bundled default (a rollback to the code's own profile).
    profile_version_id  UUID,
    revision            INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    activated_by        UUID NOT NULL,
    activated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, profile_version_id)
        REFERENCES prompt_profile_versions (tenant_id, id) ON DELETE RESTRICT
);

-- Append-only history: who moved the pointer, from what, on which evidence.
CREATE TABLE prompt_profile_activations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    profile_version_id   UUID,
    previous_version_id  UUID,
    revision             INTEGER NOT NULL,
    actor                UUID NOT NULL,
    evaluation_ref       UUID,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, profile_version_id)
        REFERENCES prompt_profile_versions (tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX prompt_profile_activations_tenant ON prompt_profile_activations (tenant_id, created_at DESC);

CREATE TABLE note_experiments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_by          UUID NOT NULL,
    -- A client retry with the same key returns the same experiment.
    idempotency_key     TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    -- [{note_id, transcript_rev, snapshot_key, sha256}] — the fixed inputs, by reference.
    sources             JSONB NOT NULL CHECK (jsonb_typeof(sources) = 'array'),
    -- [version id | null (bundled default)], in candidate order.
    candidates          JSONB NOT NULL CHECK (jsonb_typeof(candidates) = 'array'),
    repetitions         SMALLINT NOT NULL CHECK (repetitions BETWEEN 1 AND 3),
    length              TEXT NOT NULL CHECK (length IN ('short', 'standard', 'detailed')),
    output_language     TEXT NOT NULL CHECK (length(output_language) BETWEEN 2 AND 8),
    state               TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')),
    budget_cap_cents    INTEGER NOT NULL CHECK (budget_cap_cents >= 0),
    reserved_cents      NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (reserved_cents >= 0),
    spent_cents         NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (spent_cents >= 0),
    -- false when a backend has no price: cost is shown as unknown, never made up,
    -- and `token_cap` bounds the run instead.
    cost_known          BOOLEAN NOT NULL DEFAULT true,
    token_cap           INTEGER NOT NULL CHECK (token_cap > 0),
    tokens_used         INTEGER NOT NULL DEFAULT 0 CHECK (tokens_used >= 0),
    error_kind          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key)
);
-- One active experiment per workspace.
CREATE UNIQUE INDEX note_experiments_one_active
    ON note_experiments (tenant_id) WHERE state IN ('queued', 'running');
CREATE TRIGGER note_experiments_set_updated_at
    BEFORE UPDATE ON note_experiments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE note_experiment_runs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL,
    experiment_id        UUID NOT NULL,
    candidate_index      SMALLINT NOT NULL CHECK (candidate_index BETWEEN 0 AND 1),
    source_index         SMALLINT NOT NULL CHECK (source_index BETWEEN 0 AND 11),
    repetition           SMALLINT NOT NULL CHECK (repetition BETWEEN 1 AND 3),
    state                TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    -- The effective configuration this run used: version, hashes, flags, models. No text.
    config_snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config_snapshot) = 'object'),
    -- Encrypted object (tenant-prefixed key): the produced note, for side-by-side review.
    artifact_key         TEXT,
    -- Stage counts, actual models and fallbacks per call, tokens, latency. No text.
    metrics              JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
    error_kind           TEXT,
    cost_cents           NUMERIC(12, 4),
    latency_ms           INTEGER,
    started_at           TIMESTAMPTZ,
    finished_at          TIMESTAMPTZ,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, experiment_id, candidate_index, source_index, repetition),
    FOREIGN KEY (tenant_id, experiment_id) REFERENCES note_experiments (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE note_experiment_reviews (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    experiment_id   UUID NOT NULL,
    run_a_id        UUID NOT NULL,
    run_b_id        UUID NOT NULL,
    reviewer        UUID NOT NULL,
    -- Blind: labels were randomised and identities hidden until submit; revealed
    -- = the reviewer looked first. Both are stored.
    blind           BOOLEAN NOT NULL,
    revealed        BOOLEAN NOT NULL DEFAULT false,
    preference      TEXT NOT NULL CHECK (preference IN ('a', 'b', 'tie', 'neither')),
    -- [{run: a|b, label: wrong_actor|missing_condition|unsupported_claim|omission|duplicate|unclear_attribution, line?}]
    findings        JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(findings) = 'array'),
    -- May quote the source: read under the source's access rules.
    comment         TEXT NOT NULL DEFAULT '' CHECK (length(comment) <= 4000),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, experiment_id) REFERENCES note_experiments (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, run_a_id) REFERENCES note_experiment_runs (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, run_b_id) REFERENCES note_experiment_runs (tenant_id, id) ON DELETE CASCADE
);

ALTER TABLE note_generations ADD COLUMN config_snapshot JSONB
    CHECK (config_snapshot IS NULL OR jsonb_typeof(config_snapshot) = 'object');

-- Row-level security: each table sees only the current workspace's rows.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'prompt_profiles', 'prompt_profile_versions', 'prompt_profile_bindings',
        'prompt_profile_activations', 'note_experiments', 'note_experiment_runs',
        'note_experiment_reviews'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR SELECT TO app_role '
            'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            t || '_tenant_select', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR INSERT TO app_role '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            t || '_tenant_insert', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR UPDATE TO app_role '
            'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            t || '_tenant_update', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I AS RESTRICTIVE FOR ALL TO app_role '
            'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            t || '_tenant_restrictive', t);
    END LOOP;
END;
$$;

-- Saved versions, the activation history and reviews are append-only for the app.
GRANT SELECT, INSERT ON prompt_profile_versions, prompt_profile_activations,
    note_experiment_reviews TO app_role;
GRANT SELECT, INSERT, UPDATE ON prompt_profiles, prompt_profile_bindings,
    note_experiments, note_experiment_runs TO app_role;
