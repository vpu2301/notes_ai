-- 0066 — Sprint TQ3: one name, one spelling.
--
-- * `transcript_corrections` — read-time overlays on the immutable ASR
--   artefact: a name heard several ways ("Andala", "Handela") is shown as one
--   spelling ("Handala") wherever the transcript is read. Occurrences anchor
--   on the artefact's segment/word indices plus the first word's start time,
--   so speaker merges and re-labels leave them valid. Rows are content (the
--   spellings): never in logs, audit payloads or metrics.
-- * `transcription_jobs.entity_unify_status` — whether the unifier has run for
--   the job (NULL = not yet; it runs on the first result read).
-- * `transcription_jobs.corrections_rev` — bumped on every status change of a
--   correction; a PUT names the rev it saw (409 when stale). Separate from
--   `diarization_rev`, which selects the artefact object.
-- Deletion: cascades with the job. RLS: the 0052 shape (no tenant deletes).
CREATE TABLE transcript_corrections (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    job_id       UUID NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('entity')),
    from_forms   TEXT[] NOT NULL CHECK (cardinality(from_forms) BETWEEN 1 AND 32),
    to_text      TEXT NOT NULL CHECK (char_length(to_text) BETWEEN 1 AND 80),
    occurrences  JSONB NOT NULL CHECK (jsonb_typeof(occurrences) = 'array'),
    source       TEXT NOT NULL CHECK (source IN ('glossary', 'calendar', 'hint', 'majority', 'user')),
    confidence   NUMERIC(4, 3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status       TEXT NOT NULL CHECK (status IN ('proposed', 'accepted', 'rejected')),
    decided_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, to_text)
);
CREATE INDEX transcript_corrections_tenant_job_idx ON transcript_corrections (tenant_id, job_id);

ALTER TABLE transcription_jobs
    ADD COLUMN entity_unify_status TEXT
        CHECK (entity_unify_status IS NULL
               OR entity_unify_status IN ('done', 'skipped_budget', 'error')),
    ADD COLUMN corrections_rev INTEGER NOT NULL DEFAULT 0 CHECK (corrections_rev >= 0);

-- ── Row-level security (the 0052 shape) ─────────────────────────────
ALTER TABLE transcript_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_corrections FORCE  ROW LEVEL SECURITY;
CREATE POLICY transcript_corrections_tenant_select ON transcript_corrections
    FOR SELECT TO app_role USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY transcript_corrections_tenant_insert ON transcript_corrections
    FOR INSERT TO app_role WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY transcript_corrections_tenant_update ON transcript_corrections
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY transcript_corrections_tenant_delete ON transcript_corrections
    FOR DELETE TO app_role USING (false);
CREATE POLICY transcript_corrections_tenant_restrictive ON transcript_corrections
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON transcript_corrections TO app_role;
