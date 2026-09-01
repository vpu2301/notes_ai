-- 0009 — notes, note_versions, note_code_counters,
--         audit.note_chain_failures, note_synthesis_jobs.
--
-- Append-only versioning: `notes` is the head row (one per logical
-- note); `note_versions` holds the immutable history.
-- `notes.current_version_id` points at the latest version but is
-- installed as a deferrable FK so the two-step insert-note-then-
-- insert-version pattern works inside a single serializable
-- transaction (ADR-0020).
--
-- Lifecycle: draft → finalized → amended | cancelled. Finalize is a
-- plain lifecycle transition with validation; the hash-chain
-- (append-only versions, JCS canonicalisation, chain verify) is generic
-- integrity and is kept.
--
-- Denormalized columns (title) duplicate data that also lives in the
-- current version's content_jsonb; they are the columns we filter/sort
-- on, kept here for index efficiency. A daily integrity check catches
-- drift between the head and the current version.

CREATE TYPE note_status AS ENUM (
    'draft',
    'finalized',
    'amended',
    'cancelled'
);

CREATE TYPE note_amendment_type AS ENUM (
    'correction',
    'addition',
    'clarification'
);

CREATE TABLE notes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- Generated per-tenant per-year (NOTE-2026-00042).
    code                TEXT NOT NULL,

    -- FK to the current version row. NULL during the two-step insert in
    -- CreateNote; non-NULL at end of transaction (the FK is added in the
    -- note_versions section below, DEFERRABLE INITIALLY DEFERRED).
    current_version_id  UUID,

    -- Lifecycle.
    status              note_status NOT NULL DEFAULT 'draft',

    -- Authorship. Author + tenant only — a note belongs to the workspace
    -- and the people who wrote it.
    primary_author_id   UUID NOT NULL REFERENCES users(sub) ON DELETE RESTRICT,
    co_author_ids       UUID[] NOT NULL DEFAULT '{}',

    -- Template provenance.
    template_id         UUID REFERENCES templates(id) ON DELETE RESTRICT,
    template_schema_version INTEGER,

    -- Denormalized for filter/sort. Kept in sync by service layer.
    title               TEXT NOT NULL DEFAULT '',

    -- Lifecycle timestamps.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at        TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    cancelled_reason    TEXT,

    -- Dictation session that birthed this draft.
    source_session_id   UUID,

    -- Batch transcription job this note was created from ("assign
    -- transcript to a note"). Deliberately NOT an FK: notes must survive
    -- audio/job erasure (retention crypto-shreds the job's artifacts; the
    -- document created from it is retained under its own lifecycle).
    source_asr_job_id   UUID,

    -- Generated tsvector on title + code for the "type-ahead" path.
    search_vector       tsvector GENERATED ALWAYS AS (
                          to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(code, ''))
                        ) STORED,

    CONSTRAINT notes_code_per_tenant_unique UNIQUE (tenant_id, code),
    CONSTRAINT notes_status_finalized_has_ts
        CHECK ((status IN ('finalized','amended')) = (finalized_at IS NOT NULL)),
    CONSTRAINT notes_status_cancelled_has_ts
        CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);

CREATE INDEX notes_tenant_status_idx
    ON notes (tenant_id, status, created_at DESC, id);
CREATE INDEX notes_author_idx
    ON notes (tenant_id, primary_author_id, updated_at DESC);
CREATE INDEX notes_search_vector_idx
    ON notes USING gin (search_vector);
CREATE INDEX notes_updated_idx
    ON notes (tenant_id, updated_at DESC, id);
-- At most ONE note per source job per tenant, so double-clicking
-- "create note from transcript" can't fork two documents.
CREATE UNIQUE INDEX notes_source_asr_job_unique
    ON notes (tenant_id, source_asr_job_id)
    WHERE source_asr_job_id IS NOT NULL;

-- ── RLS ─────────────────────────────────────────────────────────────

ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes FORCE  ROW LEVEL SECURITY;

CREATE POLICY notes_tenant_select ON notes
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY notes_tenant_insert ON notes
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY notes_tenant_update ON notes
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY notes_tenant_delete ON notes
    FOR DELETE TO app_role
    USING (false);  -- hard delete forbidden; cancellation is the soft-delete

CREATE POLICY notes_tenant_restrictive ON notes
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON notes TO app_role;

-- ── Per-tenant code counter ────────────────────────────────────────
-- Used by ``code_sequence.next_code()`` to mint the per-year code.

CREATE TABLE note_code_counters (
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    year       INTEGER NOT NULL,
    counter    BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year)
);

ALTER TABLE note_code_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_code_counters FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_code_counters_tenant ON note_code_counters
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON note_code_counters TO app_role;

-- ── note_versions (append-only) ─────────────────────────────────────
-- Every change to a note's content emits a new row here. Rows are never
-- UPDATEd or DELETEd. The chain integrity property test (CI) + daily
-- reconciler verify this invariant.
--
-- ``parent_version_id`` chains amendments back to the finalized version
-- they amend. For non-amendment versions parent is the previous
-- version_number (always-on linear chain); for amendments parent is the
-- *finalized* version amended off, so the chain forms a tree.

CREATE TABLE note_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id             UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,

    -- 1-based, monotonic per note. (Validated by chain reconciler.)
    version_number      INTEGER NOT NULL CHECK (version_number >= 1),

    -- Parent in the version DAG.
    parent_version_id   UUID REFERENCES note_versions(id) ON DELETE RESTRICT,

    -- Who created this version + when.
    created_by          UUID NOT NULL REFERENCES users(sub) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Content body. Strict shape enforced by NoteContent Pydantic
    -- (libs/note_models). DB does not validate beyond JSON-validity.
    content_jsonb       JSONB NOT NULL,
    -- Plain-text projection of content_jsonb for FTS. Service layer
    -- maintains this; never edited by hand.
    rendered_text       TEXT NOT NULL DEFAULT '',
    -- Diff from parent_version (one entry per section change). Empty
    -- for v1. Service computes via difflib.SequenceMatcher.
    diff_jsonb          JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Free-form metadata bag (body_hash for idempotency, FE client
    -- info, source dictation segment ids, etc.). Open dict; the
    -- ``metadata.body_hash`` key is reserved for autosave idempotency.
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Amendment fields. Filled in by POST /notes/{id}/amend.
    is_amendment        BOOLEAN NOT NULL DEFAULT FALSE,
    amendment_type      note_amendment_type,
    amendment_reason    TEXT,

    -- Generated tsvector on rendered_text. Used by full-text search.
    search_vector       tsvector GENERATED ALWAYS AS (
                          to_tsvector('simple', coalesce(rendered_text, ''))
                        ) STORED,

    CONSTRAINT note_versions_unique_per_note
        UNIQUE (note_id, version_number),
    CONSTRAINT note_versions_amendment_consistency
        CHECK ((is_amendment = TRUE) = (amendment_type IS NOT NULL))
);

CREATE INDEX note_versions_note_idx
    ON note_versions (note_id, version_number DESC);
CREATE INDEX note_versions_parent_idx
    ON note_versions (parent_version_id);
CREATE INDEX note_versions_search_vector_idx
    ON note_versions USING gin (search_vector);
CREATE INDEX note_versions_metadata_body_hash_idx
    ON note_versions ((metadata->>'body_hash'));

-- Wire notes.current_version_id now that the target table exists.
ALTER TABLE notes
    ADD CONSTRAINT notes_current_version_fk
    FOREIGN KEY (current_version_id)
    REFERENCES note_versions(id)
    DEFERRABLE INITIALLY DEFERRED;

-- ── RLS via JOIN to notes.tenant_id ─────────────────────────────────
-- note_versions does not carry tenant_id (it's denormalized one row
-- away on notes). RLS therefore uses an EXISTS subquery — slower than a
-- direct column check but correct; Postgres pushes the predicate into
-- the join when the planner is happy.

ALTER TABLE note_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_versions FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_versions_tenant_select ON note_versions
    FOR SELECT TO app_role
    USING (
        EXISTS (
            SELECT 1 FROM notes n
            WHERE n.id = note_versions.note_id
              AND n.tenant_id = current_setting('app.tenant_id', true)::uuid
        )
    );

CREATE POLICY note_versions_tenant_insert ON note_versions
    FOR INSERT TO app_role
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM notes n
            WHERE n.id = note_versions.note_id
              AND n.tenant_id = current_setting('app.tenant_id', true)::uuid
        )
    );

CREATE POLICY note_versions_tenant_delete ON note_versions
    FOR DELETE TO app_role
    USING (false);  -- append-only forever

CREATE POLICY note_versions_tenant_restrictive ON note_versions
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (
        EXISTS (
            SELECT 1 FROM notes n
            WHERE n.id = note_versions.note_id
              AND n.tenant_id = current_setting('app.tenant_id', true)::uuid
        )
    );

GRANT SELECT, INSERT ON note_versions TO app_role;

-- ── Chain reconciler scratch table ──────────────────────────────────
-- A separate, audit-schema-resident table that the reconciler appends
-- to whenever it detects a chain anomaly. Source-of-truth for the chain
-- integrity dashboard + alerting; audit.events carries the same data
-- with hash-chained guarantees.
--
-- Anomaly vocabulary note: 'amendment_off_unsigned_parent' is the
-- historical name for "amendment whose parent version was never
-- finalized" (the e-signature flow is gone; finalization is the anchor).
-- Both spellings are admitted so the reconciler can migrate its
-- vocabulary without a schema change.

CREATE TABLE audit.note_chain_failures (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id     UUID NOT NULL,
    note_id       UUID NOT NULL,
    anomaly_kind  TEXT NOT NULL CHECK (anomaly_kind IN (
        'gap_in_version_numbers',
        'cycle_detected',
        'unreachable_from_head',
        'amendment_off_unsigned_parent',
        'amendment_off_unfinalized_parent',
        'multiple_genesis_versions',
        'parent_missing'
    )),
    detail_jsonb  JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_at   TIMESTAMPTZ,
    resolved_by   UUID,
    resolution_notes TEXT
);

CREATE INDEX note_chain_failures_unresolved_idx
    ON audit.note_chain_failures (detected_at DESC)
    WHERE resolved_at IS NULL;
CREATE INDEX note_chain_failures_by_note_idx
    ON audit.note_chain_failures (note_id, detected_at DESC);

GRANT SELECT, INSERT, UPDATE ON audit.note_chain_failures TO audit_writer;
GRANT SELECT ON audit.note_chain_failures TO audit_reader;

-- Same privileged roles, same per-tenant access as audit.events. The
-- reconciler SETs app.tenant_id per tenant before writing.
ALTER TABLE audit.note_chain_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.note_chain_failures FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_chain_failures_read ON audit.note_chain_failures
    FOR SELECT TO audit_writer, audit_reader
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_chain_failures_writer_insert ON audit.note_chain_failures
    FOR INSERT TO audit_writer
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_chain_failures_writer_update ON audit.note_chain_failures
    FOR UPDATE TO audit_writer
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_chain_failures_restrictive ON audit.note_chain_failures
    AS RESTRICTIVE FOR ALL TO audit_writer, audit_reader
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── note_synthesis_jobs ─────────────────────────────────────────────
-- A synthesis job is a *read-only* artefact: it records the per-section
-- synthesised text (raw dictation → clean prose) for one
-- (note, version, section set, language). It never mutates the note;
-- applying the result is done later via the draft PUT. Jobs are keyed by
-- ``request_hash`` for idempotent replay.

CREATE TABLE note_synthesis_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id             UUID NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,

    -- The note version this synthesis ran against (part of the idem key).
    version_number      INTEGER NOT NULL,
    language            TEXT NOT NULL,

    -- [{section_key, original, text}] — both the original dictation and the
    -- synthesised text so the UI can diff/revert.
    sections_jsonb      JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- sha256 over (note_id, version_number, sorted sections, language,
    -- body_hash of current content). Idempotency key.
    request_hash        TEXT NOT NULL,

    status              TEXT NOT NULL DEFAULT 'completed',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX note_synthesis_jobs_note_idx
    ON note_synthesis_jobs (tenant_id, note_id, created_at DESC);
-- Idempotency: one job per (tenant, note, request_hash).
CREATE UNIQUE INDEX note_synthesis_jobs_idem_idx
    ON note_synthesis_jobs (tenant_id, note_id, request_hash);

ALTER TABLE note_synthesis_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_synthesis_jobs FORCE  ROW LEVEL SECURITY;

CREATE POLICY note_synthesis_jobs_tenant_select ON note_synthesis_jobs
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_synthesis_jobs_tenant_insert ON note_synthesis_jobs
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY note_synthesis_jobs_tenant_delete ON note_synthesis_jobs
    FOR DELETE TO app_role
    USING (false);  -- read-only artefact; never hard-deleted by the app

CREATE POLICY note_synthesis_jobs_tenant_restrictive ON note_synthesis_jobs
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON note_synthesis_jobs TO app_role;
