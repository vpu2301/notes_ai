-- 0010 — the autocomplete subsystem: phrases, snippets, telemetry
-- (partitioned), roll-up progress, and the SECURITY DEFINER functions the
-- background jobs need (partition rotation, counter roll-up).
--
-- Three concentric scopes (ADR-0025):
--   system  → tenant_id NULL, owner_user_id NULL  (visible to everyone)
--   tenant  → tenant_id set,   owner_user_id NULL  (visible to all in tenant)
--   user    → tenant_id set,   owner_user_id set   (visible to one user)

CREATE TYPE autocomplete_source AS ENUM ('system', 'tenant', 'user');

-- ── autocomplete_phrases ────────────────────────────────────────────

CREATE TABLE autocomplete_phrases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    owner_user_id   UUID REFERENCES users(sub) ON DELETE CASCADE,
    phrase          TEXT NOT NULL,
    language        TEXT NOT NULL CHECK (language IN ('uk', 'en')),
    -- Coarse topical facet ('general', 'meetings', 'sales', …).
    specialty       TEXT,
    -- Which template section the phrase best fits ('summary', 'action_items', …).
    section_hint    TEXT,
    source          autocomplete_source NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,

    -- Ranking counters (eventually-consistent — updated nightly by the
    -- roll-up job from the telemetry partitions).
    impression_count BIGINT NOT NULL DEFAULT 0,
    acceptance_count BIGINT NOT NULL DEFAULT 0,
    last_accepted_at TIMESTAMPTZ,

    -- Provenance: where a phrase came from and its review status. The
    -- serving path only ever reads review_state='accepted' rows.
    source_kind     TEXT        NOT NULL DEFAULT 'authored'
                        CHECK (source_kind IN
                            ('mined', 'telemetry_gap', 'terminology',
                             'generated', 'authored', 'seed')),
    source_ref      TEXT,
    tier            SMALLINT    CHECK (tier IS NULL OR tier BETWEEN 1 AND 3),
    review_state    TEXT        NOT NULL DEFAULT 'accepted'
                        CHECK (review_state IN
                            ('candidate', 'accepted', 'rejected', 'retired')),
    reviewed_by     UUID,               -- soft reference (users.sub)
    reviewed_at     TIMESTAMPTZ,
    review_engine   TEXT,               -- 'human' | 'jury:<model>:<prompt_version>'
    corpus_release  TEXT,
    risk_flags      TEXT[]      NOT NULL DEFAULT '{}',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT phrase_max_80_chars CHECK (char_length(phrase) BETWEEN 1 AND 80),
    CONSTRAINT user_phrases_have_owner CHECK (
        (source = 'user'  AND owner_user_id IS NOT NULL AND tenant_id IS NOT NULL)
        OR (source = 'tenant' AND owner_user_id IS NULL AND tenant_id IS NOT NULL)
        OR (source = 'system' AND owner_user_id IS NULL AND tenant_id IS NULL)
    ),
    CONSTRAINT phrase_acceptance_lte_impression CHECK (acceptance_count <= impression_count),
    -- Risk-flagged rows are human-mandatory: tier 3 or bust.
    CONSTRAINT phrases_risk_tier_chk CHECK (cardinality(risk_flags) = 0 OR tier = 3)
);

CREATE INDEX autocomplete_phrases_corpus_idx
    ON autocomplete_phrases (tenant_id, language, source, enabled);
CREATE INDEX autocomplete_phrases_user_scope_idx
    ON autocomplete_phrases (tenant_id, owner_user_id)
    WHERE owner_user_id IS NOT NULL;
-- One phrase per (scope, language). Nil-uuid coalesce because a UNIQUE
-- constraint treats NULLs as distinct.
CREATE UNIQUE INDEX autocomplete_phrases_unique_phrase_per_owner
    ON autocomplete_phrases (
        coalesce(tenant_id,     '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid),
        phrase, language
    );
-- Admin search UI (trigram), not on the hot path.
CREATE INDEX autocomplete_phrases_trgm_idx
    ON autocomplete_phrases USING gin (phrase gin_trgm_ops);
-- Serving index: fetch_corpus() filters language + enabled + scope and
-- review_state; partial index keeps the hot path tight.
CREATE INDEX autocomplete_phrases_serving_idx
    ON autocomplete_phrases (tenant_id, language, source, enabled)
    WHERE review_state = 'accepted';

-- ── RLS ─────────────────────────────────────────────────────────────
-- Postgres requires at least one PERMISSIVE policy per command for
-- access (restrictive-only = deny-all): the PERMISSIVE app_insert/
-- app_update policies draw the coarse tenant boundary and the
-- RESTRICTIVE ones AND in the fine-grained rules (user rows only by
-- owner, tenant rows only by admins, system rows never for app_role —
-- system rows have tenant_id NULL so they fail the tenant match).

ALTER TABLE autocomplete_phrases ENABLE ROW LEVEL SECURITY;
ALTER TABLE autocomplete_phrases FORCE  ROW LEVEL SECURITY;

-- PERMISSIVE: visibility model (system + own tenant).
CREATE POLICY tenant_visibility ON autocomplete_phrases
    FOR SELECT TO app_role
    USING (
        source = 'system'
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );

CREATE POLICY app_insert_phrases ON autocomplete_phrases
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY app_update_phrases ON autocomplete_phrases
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- RESTRICTIVE write rules.
CREATE POLICY write_user_phrases ON autocomplete_phrases
    AS RESTRICTIVE
    FOR INSERT TO app_role
    WITH CHECK (
        (
            source = 'user'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND owner_user_id = current_setting('app.user_id', true)::uuid
        )
        OR (
            source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND owner_user_id IS NULL
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin')
        )
    );

CREATE POLICY update_user_phrases ON autocomplete_phrases
    AS RESTRICTIVE
    FOR UPDATE TO app_role
    USING (
        (source = 'user'
         AND tenant_id = current_setting('app.tenant_id', true)::uuid
         AND owner_user_id = current_setting('app.user_id', true)::uuid)
        OR (source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin'))
    )
    WITH CHECK (
        (source = 'user'
         AND tenant_id = current_setting('app.tenant_id', true)::uuid
         AND owner_user_id = current_setting('app.user_id', true)::uuid)
        OR (source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin'))
    );

-- DELETE: forbidden via app_role. Soft-delete with UPDATE enabled=false.
CREATE POLICY delete_forbidden ON autocomplete_phrases
    FOR DELETE TO app_role
    USING (false);

GRANT SELECT, INSERT, UPDATE ON autocomplete_phrases TO app_role;

-- tenant_writer seed role: system-source rows only. The role is
-- bootstrapped in infra/postgres/init.sql — never CREATE ROLE it here.
GRANT SELECT, INSERT, UPDATE ON autocomplete_phrases TO tenant_writer;
CREATE POLICY seed_system_rows ON autocomplete_phrases
    FOR INSERT TO tenant_writer
    WITH CHECK (source = 'system');
CREATE POLICY seed_system_select ON autocomplete_phrases
    FOR SELECT TO tenant_writer USING (true);
CREATE POLICY seed_system_update ON autocomplete_phrases
    FOR UPDATE TO tenant_writer USING (source = 'system') WITH CHECK (source = 'system');

-- ── autocomplete_snippets ───────────────────────────────────────────
-- Snippets are short triggers (e.g. "/agenda") that expand to longer
-- text. Same three-scope model as phrases.

CREATE TABLE autocomplete_snippets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    owner_user_id   UUID REFERENCES users(sub) ON DELETE CASCADE,
    trigger         TEXT NOT NULL,
    expansion       TEXT NOT NULL,
    cursor_position INTEGER NOT NULL DEFAULT 0,
    language        TEXT NOT NULL CHECK (language IN ('uk', 'en')),
    source          autocomplete_source NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT trigger_format CHECK (trigger ~ '^[a-z][a-z0-9_-]{0,30}$'),
    CONSTRAINT expansion_max CHECK (char_length(expansion) BETWEEN 1 AND 4000),
    CONSTRAINT user_snippets_have_owner CHECK (
        (source = 'user'   AND owner_user_id IS NOT NULL AND tenant_id IS NOT NULL)
        OR (source = 'tenant' AND owner_user_id IS NULL AND tenant_id IS NOT NULL)
        OR (source = 'system' AND owner_user_id IS NULL AND tenant_id IS NULL)
    )
);

CREATE UNIQUE INDEX autocomplete_snippets_unique_trigger_per_owner
    ON autocomplete_snippets (
        coalesce(tenant_id,     '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid),
        trigger, language
    );

ALTER TABLE autocomplete_snippets ENABLE ROW LEVEL SECURITY;
ALTER TABLE autocomplete_snippets FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_visibility ON autocomplete_snippets
    FOR SELECT TO app_role
    USING (
        source = 'system'
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );

CREATE POLICY app_insert_snippets ON autocomplete_snippets
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY app_update_snippets ON autocomplete_snippets
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY write_user_snippets ON autocomplete_snippets
    AS RESTRICTIVE FOR INSERT TO app_role
    WITH CHECK (
        (source = 'user'
         AND tenant_id = current_setting('app.tenant_id', true)::uuid
         AND owner_user_id = current_setting('app.user_id', true)::uuid)
        OR (source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND owner_user_id IS NULL
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin'))
    );

CREATE POLICY update_user_snippets ON autocomplete_snippets
    AS RESTRICTIVE FOR UPDATE TO app_role
    USING (
        (source = 'user'
         AND tenant_id = current_setting('app.tenant_id', true)::uuid
         AND owner_user_id = current_setting('app.user_id', true)::uuid)
        OR (source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin'))
    )
    WITH CHECK (
        (source = 'user'
         AND tenant_id = current_setting('app.tenant_id', true)::uuid
         AND owner_user_id = current_setting('app.user_id', true)::uuid)
        OR (source = 'tenant'
            AND tenant_id = current_setting('app.tenant_id', true)::uuid
            AND current_setting('app.user_role', true) IN ('admin', 'tenant_admin'))
    );

CREATE POLICY snippets_delete_forbidden ON autocomplete_snippets
    FOR DELETE TO app_role USING (false);

GRANT SELECT, INSERT, UPDATE ON autocomplete_snippets TO app_role;
GRANT SELECT, INSERT, UPDATE ON autocomplete_snippets TO tenant_writer;

CREATE POLICY seed_system_snippets_select ON autocomplete_snippets
    FOR SELECT TO tenant_writer USING (true);
CREATE POLICY seed_system_snippets_insert ON autocomplete_snippets
    FOR INSERT TO tenant_writer
    WITH CHECK (source = 'system');
CREATE POLICY seed_system_snippets_update ON autocomplete_snippets
    FOR UPDATE TO tenant_writer USING (source = 'system') WITH CHECK (source = 'system');

-- ── autocomplete_telemetry (partitioned monthly) ────────────────────
-- High-volume event log. tenant_id is on every row; reads always filter
-- by tenant_id. No RLS (documented exception per ADR-0025); the
-- RLS-policy CI gate has this table's prefix whitelisted.
--
-- `source` separates trie-suggestion telemetry ('autocomplete', the
-- default) from generative ghost text ('layer_c'). layer_c rows carry NO
-- phrase_id/snippet_id (completions are not corpus rows) — the roll-up's
-- phrase counters filter on source, and the acceptance-rate gauge reads
-- layer_c rows only.

CREATE TABLE autocomplete_telemetry (
    id              BIGSERIAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id       UUID NOT NULL,
    user_id         UUID NOT NULL,
    request_id      UUID NOT NULL,
    event_type      TEXT NOT NULL CHECK (event_type IN ('shown_only', 'accepted', 'rejected', 'timeout')),
    phrase_id       UUID,                 -- null when snippet
    snippet_id      UUID,                 -- null when phrase
    prefix_scrubbed TEXT NOT NULL,        -- personal data scrubbed before insert
    context_jsonb   JSONB NOT NULL DEFAULT '{}'::jsonb,
    source          TEXT NOT NULL DEFAULT 'autocomplete'
                        CHECK (source IN ('autocomplete', 'layer_c')),

    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX autocomplete_telemetry_phrase_idx
    ON autocomplete_telemetry (phrase_id, created_at DESC)
    WHERE event_type = 'accepted';
CREATE INDEX autocomplete_telemetry_tenant_idx
    ON autocomplete_telemetry (tenant_id, created_at DESC);
CREATE INDEX autocomplete_telemetry_user_idx
    ON autocomplete_telemetry (user_id, created_at DESC);
CREATE INDEX autocomplete_telemetry_snippet_idx
    ON autocomplete_telemetry (snippet_id, created_at DESC)
    WHERE event_type = 'accepted' AND snippet_id IS NOT NULL;

GRANT SELECT, INSERT ON autocomplete_telemetry TO app_role;
GRANT USAGE ON SEQUENCE autocomplete_telemetry_id_seq TO app_role;

-- Rollup completion markers — idempotency for the nightly job.
CREATE TABLE autocomplete_rollup_progress (
    rollup_date     DATE NOT NULL,
    tenant_id       UUID NOT NULL,
    finished_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    events_processed BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (rollup_date, tenant_id)
);
GRANT SELECT, INSERT ON autocomplete_rollup_progress TO app_role;

-- ── Sanctioned DDL path for partition rotation ──────────────────────
-- The in-service rotation job runs as app_role, which owns no DDL. This
-- SECURITY DEFINER function is deliberately narrow: it can only create
-- month-boundary partitions of autocomplete_telemetry, with the name
-- derived server-side from the validated bounds. Each new partition is
-- GRANTed SELECT to app_role because the cold-archive export reads the
-- partition DIRECTLY (the export is cross-tenant by definition and the
-- parent's per-tenant filtering would blank it).

CREATE OR REPLACE FUNCTION autocomplete_create_telemetry_partition(
    p_start date,
    p_end   date
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_name text;
BEGIN
    IF date_trunc('month', p_start)::date <> p_start
       OR (p_start + interval '1 month')::date <> p_end THEN
        RAISE EXCEPTION
            'partition bounds must be consecutive month starts, got % .. %',
            p_start, p_end;
    END IF;
    v_name := 'autocomplete_telemetry_' || to_char(p_start, 'YYYY_MM');
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF autocomplete_telemetry '
        'FOR VALUES FROM (%L) TO (%L)',
        v_name, p_start, p_end
    );
    EXECUTE format('GRANT SELECT ON %I TO app_role', v_name);
    RETURN v_name;
END;
$$;

REVOKE ALL ON FUNCTION autocomplete_create_telemetry_partition(date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION autocomplete_create_telemetry_partition(date, date) TO app_role;

-- Retention leg: only drops monthly partitions whose RANGE ended more
-- than 90 days ago; name derived server-side. Cold-storage archival
-- happens before the drop.
CREATE OR REPLACE FUNCTION autocomplete_drop_telemetry_partition(
    p_start date
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_name text;
    v_end  date;
BEGIN
    IF date_trunc('month', p_start)::date <> p_start THEN
        RAISE EXCEPTION 'partition start must be a month boundary, got %', p_start;
    END IF;
    v_end := (p_start + interval '1 month')::date;
    IF v_end > (now()::date - 90) THEN
        RAISE EXCEPTION
            'refusing to drop partition ending % — inside the 90-day retention window',
            v_end;
    END IF;
    v_name := 'autocomplete_telemetry_' || to_char(p_start, 'YYYY_MM');
    IF to_regclass(v_name) IS NULL THEN
        RETURN NULL; -- already gone: idempotent
    END IF;
    EXECUTE format(
        'ALTER TABLE autocomplete_telemetry DETACH PARTITION %I', v_name
    );
    EXECUTE format('DROP TABLE %I', v_name);
    RETURN v_name;
END;
$$;

REVOKE ALL ON FUNCTION autocomplete_drop_telemetry_partition(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION autocomplete_drop_telemetry_partition(date) TO app_role;

-- Seed two partitions: current + next month (relative to migration time
-- so a fresh stack always has a landing partition).
SELECT autocomplete_create_telemetry_partition(
    date_trunc('month', now())::date,
    (date_trunc('month', now()) + interval '1 month')::date
);
SELECT autocomplete_create_telemetry_partition(
    (date_trunc('month', now()) + interval '1 month')::date,
    (date_trunc('month', now()) + interval '2 months')::date
);

-- ── Sanctioned counter-bump path for the nightly roll-up ────────────
-- The roll-up runs as app_role under tenant_connection; the RESTRICTIVE
-- update policy correctly blocks it from touching *system* phrases, so
-- the counter UPDATE must go through this narrow SECURITY DEFINER
-- function: it can ONLY increment the three counter columns, and only
-- on rows the calling tenant may see (system rows or the tenant's own).
--
-- last_accepted_at semantics (hard-won):
--   * GREATEST, not plain COALESCE — a manual roll-up re-run for an OLD
--     day must never move last_accepted_at BACKWARDS (that would
--     re-inflate the recency-boost window).
--   * NULLIF collapses the '-infinity' comparison sentinel back to NULL
--     on store — asyncpg decodes '-infinity' as a timezone-naive
--     datetime and the ranking path then raises TypeError against its
--     aware now().

CREATE OR REPLACE FUNCTION autocomplete_bump_phrase_counters(
    p_phrase_id     uuid,
    p_impressions   bigint,
    p_accepts       bigint,
    p_last_accepted timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_impressions < 0 OR p_accepts < 0 OR p_accepts > p_impressions THEN
        RAISE EXCEPTION 'invalid counter deltas: impressions=%, accepts=%',
            p_impressions, p_accepts;
    END IF;
    UPDATE autocomplete_phrases
       SET impression_count = impression_count + p_impressions,
           acceptance_count = acceptance_count + p_accepts,
           last_accepted_at = NULLIF(
               GREATEST(
                   COALESCE(last_accepted_at, '-infinity'::timestamptz),
                   COALESCE(p_last_accepted,  '-infinity'::timestamptz)
               ),
               '-infinity'::timestamptz
           ),
           updated_at       = now()
     WHERE id = p_phrase_id
       AND (
           source = 'system'::autocomplete_source
           OR tenant_id = (current_setting('app.tenant_id', true))::uuid
       );
    RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION autocomplete_bump_phrase_counters(uuid, bigint, bigint, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION autocomplete_bump_phrase_counters(uuid, bigint, bigint, timestamptz) TO app_role;
