-- 0052 — Sprint 33: the document engine's sidecar.
--
-- Two tables beside the note, never inside it. `NoteContent` is
-- hash-chained and `extra="forbid"` (ADR-0020): a generation's
-- bookkeeping and its per-line evidence are not part of the record the
-- chain commits to, and putting them there would mean a schema change
-- every time the engine learns something.
--
-- `note_generations` is one run. It carries progress (so a client can
-- say "4 of 10 parts"), which minutes could NOT be processed
-- (`failed_ranges` — ranges only, never text), and what produced it
-- (`prompt_version`, `backend`, `model_id`) so a result can be traced
-- to the exact wording and model that made it.
--
-- `note_generated_items` is one verified fact, with the words that
-- prove it. `quote` and `text` ARE content: never logged, never
-- audited, cascade-deleted with the note, in the DSAR export.
--
-- `item_key` is the same hash every other projection uses
-- (`action_items.item_key`), so a generated task, the recipient's
-- confirmation of it, a correction to it and a carried-over copy are
-- all the same line.

CREATE TABLE note_generations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id         UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    job_id          UUID NOT NULL,
    requested_by    UUID NOT NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('auto','regenerate','transcript_changed')),
    status          TEXT NOT NULL
        CHECK (status IN ('queued','running','partial','complete','failed','superseded')),
    step            TEXT CHECK (step IS NULL OR step IN ('extract','write_items','reduce','write_doc')),
    windows_total   SMALLINT,
    windows_done    SMALLINT,
    windows_failed  SMALLINT,
    -- [[start_ms,end_ms],…] — which minutes are missing, so the note can
    -- say so instead of apologising in general. No text.
    failed_ranges   JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(failed_ranges) = 'array'),
    prompt_version  TEXT NOT NULL,
    backend         TEXT,
    model_id        TEXT,
    -- The ASR view this was built from; a later re-labelling makes the
    -- generation stale and the client offers to regenerate.
    transcript_rev  INTEGER NOT NULL DEFAULT 1,
    snapshot_key    TEXT,
    -- Counts, tokens, seconds and the section hashes the writer compares
    -- against. Never content.
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(stats) = 'object'),
    error_kind      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX note_generations_note_idx ON note_generations (note_id, created_at DESC);
-- One live generation per note: the 409 the regenerate route returns is
-- this index, not a race-prone SELECT.
CREATE UNIQUE INDEX note_generations_live_idx
    ON note_generations (note_id) WHERE status IN ('queued','running');

CREATE TABLE note_generated_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id         UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    generation_id   UUID NOT NULL REFERENCES note_generations(id) ON DELETE CASCADE,
    item_key        TEXT NOT NULL CHECK (char_length(item_key) <= 64),
    kind            TEXT NOT NULL CHECK (char_length(kind) <= 32),
    section_key     TEXT NOT NULL CHECK (char_length(section_key) <= 64),
    text            TEXT NOT NULL,
    owner_label     TEXT CHECK (owner_label IS NULL OR char_length(owner_label) <= 60),
    due_text        TEXT CHECK (due_text IS NULL OR char_length(due_text) <= 120),
    due_date        DATE,
    explicit        BOOLEAN NOT NULL DEFAULT false,
    confidence      REAL NOT NULL DEFAULT 0.7,
    flags           TEXT[] NOT NULL DEFAULT '{}',
    -- The words that prove it. A row without one cannot exist: the
    -- pipeline drops any claim whose quote is not in the transcript.
    quote           TEXT NOT NULL,
    start_ms        INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms          INTEGER NOT NULL CHECK (end_ms >= 0),
    speaker_label   TEXT,
    speaker_name    TEXT,
    -- `written` is in the note; `suggested` is offered because the
    -- author had already written in that section; `dismissed` is the
    -- author saying no (Sprint 35); `superseded` is an older run's.
    placement       TEXT NOT NULL
        CHECK (placement IN ('written','suggested','dismissed','superseded')),
    -- Sprint 36: what may leave the workspace.
    audience        TEXT NOT NULL DEFAULT 'all' CHECK (audience IN ('all','internal')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (note_id, generation_id, item_key)
);
CREATE INDEX note_generated_items_note_idx
    ON note_generated_items (note_id) WHERE placement IN ('written','suggested');

-- ── Row-level security (the 0037 shape) ─────────────────────────────
ALTER TABLE note_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_generations FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_generations_tenant_select ON note_generations
    FOR SELECT TO app_role USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generations_tenant_insert ON note_generations
    FOR INSERT TO app_role WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generations_tenant_update ON note_generations
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generations_tenant_delete ON note_generations
    FOR DELETE TO app_role USING (false);
CREATE POLICY note_generations_tenant_restrictive ON note_generations
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON note_generations TO app_role;

ALTER TABLE note_generated_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_generated_items FORCE  ROW LEVEL SECURITY;
CREATE POLICY note_generated_items_tenant_select ON note_generated_items
    FOR SELECT TO app_role USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generated_items_tenant_insert ON note_generated_items
    FOR INSERT TO app_role WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generated_items_tenant_update ON note_generated_items
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY note_generated_items_tenant_delete ON note_generated_items
    FOR DELETE TO app_role USING (false);
CREATE POLICY note_generated_items_tenant_restrictive ON note_generated_items
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON note_generated_items TO app_role;
