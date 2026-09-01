-- 0006 — `dictation_sessions`: the row that records every streaming
-- dictation lifecycle.
--
-- Wire protocol notes (see docs/api/dictation-ws-v1.md):
--   - status transitions: creating → active → (paused ⇄ active) →
--     (reconnecting → active) → finalized | abandoned | failed
--   - transcript_jsonb holds the committed (final) tokens; partials
--     are NOT persisted. NLP annotations land here too.
--   - audio_file_id is NULL until finalize; on abandon it stays NULL.
--   - worker_id is the dictation/asr-worker that owns the live inference
--     state; on worker death the session moves to failed (or abandoned
--     if the user never reconnects).
--   - `mode` distinguishes single-voice dictation from multi-speaker
--     conversation (meeting) sessions; orthogonal to target_kind (what
--     artefact the session produces). Diarization labels speakers
--     neutrally (SPEAKER_1..N); mapping to names is client-supplied.

CREATE TABLE dictation_sessions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants(id),
    user_id              UUID NOT NULL,                    -- Keycloak sub
    target_kind          TEXT NOT NULL CHECK (target_kind IN ('note','generic'))
                              DEFAULT 'generic',
    template_id          UUID,                             -- soft FK to templates
    language             TEXT NOT NULL CHECK (language IN ('uk','en','de')),
    model                TEXT NOT NULL DEFAULT 'large-v3',
    worker_id            TEXT,                             -- set on accept

    mode                 TEXT NOT NULL DEFAULT 'dictation'
                              CHECK (mode IN ('dictation', 'conversation')),

    status               TEXT NOT NULL CHECK (status IN
                              ('creating','active','paused','reconnecting',
                               'finalized','abandoned','failed'))
                              DEFAULT 'creating',

    transcript_jsonb     JSONB NOT NULL DEFAULT '[]'::jsonb,
    audio_file_id        UUID REFERENCES audio_files(id),

    -- Timing / quality metrics (populated incrementally)
    total_audio_ms       INTEGER NOT NULL DEFAULT 0,
    total_speech_ms      INTEGER NOT NULL DEFAULT 0,
    avg_partial_latency_ms INTEGER,
    avg_final_latency_ms INTEGER,
    rtf                  NUMERIC(6,3),

    -- Resilience counters
    network_drop_count   INTEGER NOT NULL DEFAULT 0,
    truncated            BOOLEAN NOT NULL DEFAULT false,

    -- Failure detail (for status=failed)
    error_kind           TEXT,
    error_detail         TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at           TIMESTAMPTZ,
    last_active_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at         TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX dictation_sessions_tenant_user_idx
    ON dictation_sessions (tenant_id, user_id, created_at DESC);
CREATE INDEX dictation_sessions_status_idx
    ON dictation_sessions (status)
    WHERE status IN ('active','paused','reconnecting','creating');
CREATE INDEX dictation_sessions_worker_idx
    ON dictation_sessions (worker_id)
    WHERE worker_id IS NOT NULL;
CREATE INDEX dictation_sessions_resume_idx
    ON dictation_sessions (tenant_id, user_id, last_active_at DESC)
    WHERE status IN ('active','paused','reconnecting');
-- Ops queries slice live sessions by mode (mode-aware capacity panels).
CREATE INDEX dictation_sessions_mode_idx
    ON dictation_sessions (tenant_id, mode, created_at DESC);

CREATE TRIGGER dictation_sessions_set_updated_at
    BEFORE UPDATE ON dictation_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT, INSERT, UPDATE ON dictation_sessions TO app_role;

ALTER TABLE dictation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE dictation_sessions FORCE  ROW LEVEL SECURITY;

CREATE POLICY dictation_sessions_tenant_select ON dictation_sessions
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY dictation_sessions_tenant_insert ON dictation_sessions
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY dictation_sessions_tenant_update ON dictation_sessions
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY dictation_sessions_tenant_restrictive ON dictation_sessions
    AS RESTRICTIVE FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── Stale-session reaper ────────────────────────────────────────────
-- Same shape, and same reason, as the ASR job reaper (0005): the reaper
-- must answer "which tenants have sessions that might be stranded?"
-- BEFORE it can open a tenant-scoped connection — an inherently
-- cross-tenant question. SECURITY DEFINER is the only sanctioned way to
-- see across tenants; nothing but tenant IDs leaves the function.

CREATE OR REPLACE FUNCTION dictation_tenants_with_stale_sessions(
    grace_seconds DOUBLE PRECISION
)
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT d.tenant_id
      FROM dictation_sessions d
     WHERE d.status IN ('creating', 'active', 'paused', 'reconnecting')
       AND d.last_active_at < now() - make_interval(secs => grace_seconds);
$$;

REVOKE ALL ON FUNCTION dictation_tenants_with_stale_sessions(DOUBLE PRECISION) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dictation_tenants_with_stale_sessions(DOUBLE PRECISION) TO app_role;
