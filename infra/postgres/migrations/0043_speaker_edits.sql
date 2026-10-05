-- 0043 — Speaker edit overlay (Sprint 28).
--
-- Edits to a diarized transcript (merge now, reassign from Sprint 30) are
-- an ordered, reversible overlay folded in at read time. The stored
-- transcript artifact is never rewritten. An edit applies to one
-- diarization run: `result_rev` must equal the job's `diarization_rev`
-- (a re-run in Sprint 29 bumps it and leaves older edits inert).
-- Rows carry labels only, never names or text.

CREATE TABLE transcription_speaker_edits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    job_id          UUID NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    result_rev      INTEGER NOT NULL DEFAULT 1,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('merge', 'reassign')),
    from_label      TEXT CHECK (from_label IS NULL OR from_label ~ '^SPEAKER_[1-9][0-9]{0,2}$'),
    to_label        TEXT CHECK (to_label   IS NULL OR to_label   ~ '^SPEAKER_[1-9][0-9]{0,2}$'),
    segment_indices INTEGER[],
    actor_sub       UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reverted_at     TIMESTAMPTZ,
    UNIQUE (job_id, seq),
    CHECK (kind <> 'merge' OR (from_label IS NOT NULL AND to_label IS NOT NULL
                               AND from_label <> to_label))
);

CREATE INDEX transcription_speaker_edits_job_idx
    ON transcription_speaker_edits (job_id, seq) WHERE reverted_at IS NULL;

GRANT SELECT, INSERT, UPDATE ON transcription_speaker_edits TO app_role;

ALTER TABLE transcription_speaker_edits ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcription_speaker_edits FORCE  ROW LEVEL SECURITY;

CREATE POLICY transcription_speaker_edits_tenant_select ON transcription_speaker_edits
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_speaker_edits_tenant_insert ON transcription_speaker_edits
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_speaker_edits_tenant_update ON transcription_speaker_edits
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY transcription_speaker_edits_tenant_restrictive ON transcription_speaker_edits
    AS RESTRICTIVE FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE transcription_jobs ADD COLUMN diarization_rev INTEGER NOT NULL DEFAULT 1;
