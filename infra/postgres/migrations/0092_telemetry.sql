-- 0092 — Telemetry sprint 1: per-run pipeline telemetry, schema v1
-- (telemetry-sprints/design/SCHEMA_v1.md, STORAGE.md). Additive only.
-- Rows hold counts, durations, enums and ids — never audio, transcript text, prompts, note
-- content, names or credentials (telemetry.redact runs before every write).
-- recording_id = transcription_jobs.id; ON DELETE CASCADE: telemetry dies with the recording.
-- Missing is not zero: a NULL measurement has its reason in null_reasons / attributes._reasons.

CREATE TABLE telemetry_runs (
    processing_run_id         UUID PRIMARY KEY,
    tenant_id                 UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    recording_id              UUID NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    note_id                   UUID,
    note_generation_id        UUID,
    kind                      TEXT NOT NULL CHECK (kind IN ('initial','reprocess')),
    reprocess_scope           TEXT CHECK (reprocess_scope IN ('diarization','notes')),
    trigger                   TEXT NOT NULL CHECK (trigger IN ('auto','user','retry','migration')),
    telemetry_schema_version  SMALLINT NOT NULL DEFAULT 1,
    -- Worker pickups of this run (queue redeliveries reuse the run and add one).
    attempts                  INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    status                    TEXT NOT NULL
                                  CHECK (status IN ('queued','running','succeeded','failed','cancelled','partial')),
    error_category            TEXT CHECK (error_category IN ('input','upload','queue','model_load','asr','diarization','postprocess','llm','storage','client','unknown')),
    submitted_at              TIMESTAMPTZ NOT NULL,
    started_at                TIMESTAMPTZ,
    finished_at               TIMESTAMPTZ,
    processing_wall_seconds   DOUBLE PRECISION,
    user_wait_seconds         DOUBLE PRECISION,
    time_to_transcript_seconds      DOUBLE PRECISION,
    time_to_speaker_labels_seconds  DOUBLE PRECISION,
    time_to_notes_seconds     DOUBLE PRECISION,
    rtf                       DOUBLE PRECISION,
    speedup                   DOUBLE PRECISION,
    audio_duration_seconds    DOUBLE PRECISION,
    asr_audio_processed_seconds DOUBLE PRECISION,
    created_by                UUID,
    concurrent_runs_at_start  INTEGER,
    other_model_activity      JSONB NOT NULL DEFAULT '[]'::jsonb,
    telemetry_overhead_seconds  DOUBLE PRECISION,
    telemetry_buffer_peak_bytes BIGINT,
    retention_until           TIMESTAMPTZ NOT NULL,
    trace_id                  TEXT CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'),
    null_reasons              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX telemetry_runs_recording_idx ON telemetry_runs (tenant_id, recording_id, submitted_at DESC);
CREATE INDEX telemetry_runs_open_idx ON telemetry_runs (status) WHERE status IN ('queued','running');
CREATE INDEX telemetry_runs_retention_idx ON telemetry_runs (retention_until);

CREATE TABLE telemetry_run_contexts (
    processing_run_id     UUID PRIMARY KEY REFERENCES telemetry_runs(processing_run_id) ON DELETE CASCADE,
    tenant_id             UUID NOT NULL,
    telemetry_schema_version SMALLINT NOT NULL DEFAULT 1,
    app_commit            TEXT,
    app_build             TEXT,
    os_name               TEXT,
    os_version            TEXT,
    arch                  TEXT,
    chip_model            TEXT,
    memory_total_bytes    BIGINT,
    execution_mode        TEXT NOT NULL CHECK (execution_mode IN ('native','container','remote')),
    effective_config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    device_asr            JSONB,
    device_diarization    JSONB,
    device_llm            JSONB,
    memory_pressure_start TEXT,
    memory_pressure_end   TEXT,
    process_rss_start     BIGINT,
    process_rss_end       BIGINT,
    swap_used_start       BIGINT,
    swap_used_end         BIGINT,
    container_mem_limit   BIGINT,
    null_reasons          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE telemetry_spans (
    span_id            UUID PRIMARY KEY,
    processing_run_id  UUID NOT NULL REFERENCES telemetry_runs(processing_run_id) ON DELETE CASCADE,
    tenant_id          UUID NOT NULL,
    parent_span_id     UUID,
    stage              TEXT NOT NULL CHECK (stage IN ('capture_input','upload','queue','model_init','audio_prep','vad','language_detection','asr_primary','asr_recovery','diarization_load','diarization_infer','postprocess_align','postprocess_attribute','postprocess_cleanup','persist','llm_call','ui_delivery','other')),
    name               TEXT NOT NULL CHECK (char_length(name) <= 128),
    attempt            INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    status             TEXT NOT NULL CHECK (status IN ('ok','error','cancelled','skipped','partial','started')),
    error_category     TEXT CHECK (error_category IN ('input','upload','queue','model_load','asr','diarization','postprocess','llm','storage','client','unknown')),
    error_class        TEXT CHECK (char_length(error_class) <= 128),
    start_monotonic_ns BIGINT,
    end_monotonic_ns   BIGINT,
    start_wall_utc     TIMESTAMPTZ,
    end_wall_utc       TIMESTAMPTZ,
    clock_source       TEXT NOT NULL CHECK (clock_source IN ('monotonic','wall','client_wall')),
    process_id         INTEGER NOT NULL,
    host               TEXT NOT NULL CHECK (char_length(host) <= 128),
    attributes         JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_parallel_with   UUID[]
);
CREATE INDEX telemetry_spans_run_idx ON telemetry_spans (processing_run_id);
CREATE INDEX telemetry_spans_stage_idx ON telemetry_spans (stage, start_wall_utc);

CREATE TABLE telemetry_llm_calls (
    llm_call_id        UUID PRIMARY KEY,
    span_id            UUID NOT NULL,
    processing_run_id  UUID NOT NULL REFERENCES telemetry_runs(processing_run_id) ON DELETE CASCADE,
    tenant_id          UUID NOT NULL,
    purpose            TEXT NOT NULL CHECK (purpose IN
                           ('note_write','note_merge','note_check','note_ask','provider_probe','inline_completion')),
    provider           TEXT NOT NULL,
    model              TEXT,
    backend            TEXT NOT NULL,
    execution_mode     TEXT NOT NULL CHECK (execution_mode IN ('native','container','remote')),
    streaming          BOOLEAN NOT NULL DEFAULT false,
    attempt            INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    status             TEXT NOT NULL CHECK (status IN ('ok','error','cancelled','skipped','partial','started')),
    queue_wait_seconds DOUBLE PRECISION,
    model_load_seconds DOUBLE PRECISION,
    time_to_first_token_seconds DOUBLE PRECISION,
    total_latency_seconds DOUBLE PRECISION,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    cached_input_tokens INTEGER,
    reasoning_tokens   INTEGER,
    token_source       TEXT NOT NULL CHECK (token_source IN ('provider','estimated')),
    token_accounting_note TEXT CHECK (char_length(token_accounting_note) <= 256),
    generation_tokens_per_second DOUBLE PRECISION,
    prompt_chars       INTEGER,
    completion_chars   INTEGER,
    error_category     TEXT CHECK (error_category IN ('input','upload','queue','model_load','asr','diarization','postprocess','llm','storage','client','unknown')),
    null_reasons       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX telemetry_llm_calls_run_idx ON telemetry_llm_calls (processing_run_id);
CREATE INDEX telemetry_llm_calls_purpose_idx ON telemetry_llm_calls (purpose, backend);

CREATE TABLE telemetry_client_events (
    event_id            UUID PRIMARY KEY,
    processing_run_id   UUID REFERENCES telemetry_runs(processing_run_id) ON DELETE CASCADE,
    recording_id        UUID NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    tenant_id           UUID NOT NULL,
    client              TEXT NOT NULL CHECK (client IN ('web','macos','ios')),
    client_version      TEXT NOT NULL CHECK (char_length(client_version) <= 64),
    event               TEXT NOT NULL CHECK (event IN ('recording_stopped','import_submitted','upload_started',
                            'upload_finished','transcript_displayed','speaker_labels_displayed','notes_displayed','error_shown')),
    client_wall_utc     TIMESTAMPTZ NOT NULL,
    client_monotonic_ns BIGINT,
    server_received_utc TIMESTAMPTZ NOT NULL,
    estimated_clock_offset_ms BIGINT NOT NULL,
    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX telemetry_client_events_run_idx ON telemetry_client_events (processing_run_id);
CREATE INDEX telemetry_client_events_recording_idx ON telemetry_client_events (tenant_id, recording_id);

ALTER TABLE telemetry_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_runs FORCE  ROW LEVEL SECURITY;
CREATE POLICY telemetry_runs_tenant_select ON telemetry_runs
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_runs_tenant_insert ON telemetry_runs
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_runs_tenant_update ON telemetry_runs
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_runs_tenant_delete ON telemetry_runs
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_runs_tenant_restrictive ON telemetry_runs
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON telemetry_runs TO app_role;

ALTER TABLE telemetry_run_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_run_contexts FORCE  ROW LEVEL SECURITY;
CREATE POLICY telemetry_run_contexts_tenant_select ON telemetry_run_contexts
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_run_contexts_tenant_insert ON telemetry_run_contexts
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_run_contexts_tenant_update ON telemetry_run_contexts
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_run_contexts_tenant_delete ON telemetry_run_contexts
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_run_contexts_tenant_restrictive ON telemetry_run_contexts
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON telemetry_run_contexts TO app_role;

ALTER TABLE telemetry_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_spans FORCE  ROW LEVEL SECURITY;
CREATE POLICY telemetry_spans_tenant_select ON telemetry_spans
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_spans_tenant_insert ON telemetry_spans
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_spans_tenant_update ON telemetry_spans
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_spans_tenant_delete ON telemetry_spans
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_spans_tenant_restrictive ON telemetry_spans
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON telemetry_spans TO app_role;

ALTER TABLE telemetry_llm_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_llm_calls FORCE  ROW LEVEL SECURITY;
CREATE POLICY telemetry_llm_calls_tenant_select ON telemetry_llm_calls
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_llm_calls_tenant_insert ON telemetry_llm_calls
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_llm_calls_tenant_update ON telemetry_llm_calls
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_llm_calls_tenant_delete ON telemetry_llm_calls
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_llm_calls_tenant_restrictive ON telemetry_llm_calls
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON telemetry_llm_calls TO app_role;

ALTER TABLE telemetry_client_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_client_events FORCE  ROW LEVEL SECURITY;
CREATE POLICY telemetry_client_events_tenant_select ON telemetry_client_events
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_client_events_tenant_insert ON telemetry_client_events
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_client_events_tenant_update ON telemetry_client_events
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_client_events_tenant_delete ON telemetry_client_events
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY telemetry_client_events_tenant_restrictive ON telemetry_client_events
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON telemetry_client_events TO app_role;

-- concurrent_runs_at_start counts open runs across every tenant (machine contention), so it
-- needs to see past RLS; it returns one number and nothing else.
CREATE FUNCTION telemetry_open_runs() RETURNS INTEGER
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT count(*)::integer FROM telemetry_runs WHERE status IN ('queued', 'running')
$$;
REVOKE ALL ON FUNCTION telemetry_open_runs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION telemetry_open_runs() TO app_role;
