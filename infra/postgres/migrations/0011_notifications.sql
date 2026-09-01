-- 0011 — the notification subsystem: notifications, preferences, user
-- settings, outbox, digest progress, dead letters, worker role + fns.
--
-- The category vocabulary below is pinned in THREE places that must
-- agree: `notification_events.Category`, `notification_service.domain.
-- catalog` (a test asserts those two are 1:1), and these CHECK
-- constraints. The constraints are the only one of the three that a
-- running system enforces — a Category member without a matching CHECK
-- entry turns every event of that category into a CheckViolationError
-- inside the consumer, then a DLQ entry, and the user hears nothing.

-- ── notifications: the per-recipient record ─────────────────────────
-- One domain fact fans out to zero or more rows here, one per recipient.
-- The row is the source of truth for the in-app feed and the badge
-- count; the WebSocket is a delivery optimisation, never the state (a
-- reconnecting client always re-reads the count from here).
--
-- `body_text` is CONTENT-FREE BY CONSTRUCTION and pre-rendered at
-- materialisation time. It carries pointers — a note code, a deep link —
-- never note content or personal data (ADR-0031). The column is
-- plaintext because it is defined to hold no sensitive content; that
-- boundary is enforced by the blocking CI gate
-- `scripts/ci/check-notification-pii-free.py`, not by encryption.
--
-- `dedupe_key` is the idempotency anchor: derived by the consumer from
-- the producer's `event_id` plus the recipient, so an at-least-once
-- redelivery of the same fact collapses onto the row already written.

CREATE TABLE notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- The Keycloak principal who should see this. FK to users(sub) —
    -- the same convention the rest of the schema uses.
    recipient_user_id   UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    category            TEXT NOT NULL
                            CHECK (category IN (
                                'note.finalized',
                                'note.amended',
                                'note.chain_failure',
                                'note.shared_with_you',
                                'dictation.completed',
                                'transcription.completed',
                                'transcription.failed',
                                'security.mfa_reminder',
                                'system.digest'
                            )),

    -- UNIQUE per tenant — see the module comment above.
    dedupe_key          TEXT NOT NULL,

    title               TEXT NOT NULL,
    body_text           TEXT NOT NULL DEFAULT '',
    deep_link           TEXT NOT NULL DEFAULT '',

    -- The allow-listed, content-free projection the title/body were
    -- rendered from (`domain/render.safe_payload`). Stored so the EMAIL
    -- channel can re-render from the same pointers later, rather than
    -- scraping them back out of a localised title string — that parse
    -- would break the moment a template's word order changed.
    render_fields       JSONB NOT NULL DEFAULT '{}'::jsonb,

    resource_type       TEXT NOT NULL DEFAULT '',
    resource_id         UUID,

    severity            TEXT NOT NULL DEFAULT 'info'
                            CHECK (severity IN ('info', 'warning', 'critical')),

    read_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The idempotency anchor. Scoped by tenant so two tenants replaying
-- unrelated events can never collide.
CREATE UNIQUE INDEX notifications_dedupe_key_unique
    ON notifications (tenant_id, dedupe_key);

-- Drives the unread-first feed. `read_at NULLS FIRST` puts unread rows
-- ahead of read ones without a second query or a UNION.
CREATE INDEX notifications_feed_idx
    ON notifications (recipient_user_id, read_at NULLS FIRST, created_at DESC);

-- Drives the badge count, which is polled far more often than the feed
-- is read. Partial so it stays small no matter how much history a
-- long-lived user accumulates.
CREATE INDEX notifications_unread_idx
    ON notifications (recipient_user_id)
    WHERE read_at IS NULL;

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications FORCE  ROW LEVEL SECURITY;

CREATE POLICY notifications_tenant_select ON notifications
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notifications_tenant_insert ON notifications
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notifications_tenant_update ON notifications
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- History is append-only from the app's perspective; expiry is a
-- retention job running as a privileged role, not a user action.
CREATE POLICY notifications_tenant_delete ON notifications
    FOR DELETE TO app_role
    USING (false);

CREATE POLICY notifications_tenant_restrictive ON notifications
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON notifications TO app_role;

-- ── app_notification_worker ─────────────────────────────────────────
-- The delivery/digest workers get their own role. They must be able to
-- materialise rows and mark deliveries, but never to erase history — so
-- a leaked worker credential cannot destroy the audit trail of what was
-- sent to whom. NOLOGIN by design until the workers split into their
-- own deploy unit; until then app_role is the actual writer.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_notification_worker') THEN
        CREATE ROLE app_notification_worker NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON notifications TO app_notification_worker;

CREATE POLICY notifications_worker_select ON notifications
    FOR SELECT TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notifications_worker_insert ON notifications
    FOR INSERT TO app_notification_worker
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notifications_worker_update ON notifications
    FOR UPDATE TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notifications_worker_restrictive ON notifications
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── notification_preferences ────────────────────────────────────────
-- One row per (user, category) OVERRIDE. ABSENT ROW MEANS "tenant
-- default", deliberately: defaults are resolved in domain/preferences.py
-- against domain/catalog.py, so shifting a category default reaches
-- every user who never expressed an opinion with no backfill.

CREATE TABLE notification_preferences (
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_id         UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    category        TEXT NOT NULL
                        CHECK (category IN (
                            'note.finalized',
                            'note.amended',
                            'note.chain_failure',
                            'note.shared_with_you',
                            'dictation.completed',
                            'transcription.completed',
                            'transcription.failed',
                            'security.mfa_reminder',
                            'system.digest'
                        )),

    in_app_enabled  BOOLEAN NOT NULL DEFAULT TRUE,

    -- `email_mode` subsumes the on/off flag: 'off' IS disabled. A
    -- separate boolean alongside a mode would allow the contradictory
    -- state (enabled=false, mode='immediate') and every reader would
    -- have to decide which wins. One column, no ambiguity.
    email_mode      TEXT NOT NULL DEFAULT 'off'
                        CHECK (email_mode IN ('immediate', 'digest', 'off')),

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, user_id, category)
);

CREATE INDEX notification_preferences_user_idx
    ON notification_preferences (tenant_id, user_id);

ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences FORCE  ROW LEVEL SECURITY;

CREATE POLICY notification_preferences_tenant_select ON notification_preferences
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_preferences_tenant_insert ON notification_preferences
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_preferences_tenant_update ON notification_preferences
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_preferences_tenant_delete ON notification_preferences
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_preferences_tenant_restrictive ON notification_preferences
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON notification_preferences TO app_role;
-- The delivery worker READS preferences to decide suppression; it never
-- writes them.
GRANT SELECT ON notification_preferences TO app_notification_worker;
CREATE POLICY notification_preferences_worker_select ON notification_preferences
    FOR SELECT TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_preferences_worker_restrictive ON notification_preferences
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── notification_user_settings ──────────────────────────────────────
-- Quiet hours defer EMAIL only; in-app is never deferred (a badge is
-- not an interruption). Stored as local wall-clock TIME plus an IANA
-- zone, not as UTC offsets: an offset breaks twice a year at the DST
-- boundary, and "no email between 22:00 and 07:00 my time" must keep
-- meaning that through the transition.

CREATE TABLE notification_user_settings (
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_id             UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    -- NULL start/end = quiet hours disabled. Both must be set together;
    -- enforced by the CHECK below rather than by app code alone.
    quiet_hours_start   TIME,
    quiet_hours_end     TIME,

    -- IANA name, e.g. 'Europe/Kyiv'. Validated by the service against
    -- zoneinfo on write; stored as text because Postgres has no tz type.
    timezone            TEXT NOT NULL DEFAULT 'UTC',

    -- Local wall-clock hour at which the daily digest is sent.
    digest_hour         SMALLINT NOT NULL DEFAULT 8
                            CHECK (digest_hour BETWEEN 0 AND 23),

    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, user_id),

    CONSTRAINT notification_user_settings_quiet_hours_paired
        CHECK ((quiet_hours_start IS NULL) = (quiet_hours_end IS NULL))
);

ALTER TABLE notification_user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_user_settings FORCE  ROW LEVEL SECURITY;

CREATE POLICY notification_user_settings_tenant_select ON notification_user_settings
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_user_settings_tenant_insert ON notification_user_settings
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_user_settings_tenant_update ON notification_user_settings
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_user_settings_tenant_delete ON notification_user_settings
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_user_settings_tenant_restrictive ON notification_user_settings
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON notification_user_settings TO app_role;
GRANT SELECT ON notification_user_settings TO app_notification_worker;
CREATE POLICY notification_user_settings_worker_select ON notification_user_settings
    FOR SELECT TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_user_settings_worker_restrictive ON notification_user_settings
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── notification_outbox ─────────────────────────────────────────────
-- One row per (notification, channel) delivery attempt. Every channel a
-- notification COULD have gone out on gets a row, including the ones
-- preference resolution decided to suppress — those are written
-- `suppressed` and never dispatched. That turns "the user says they got
-- an email after switching email off" from an unfalsifiable claim into
-- a lookup.
--
-- UNIQUE (notification_id, channel) is the delivery-idempotency anchor:
-- re-driving the worker over the same row cannot produce a second send.
-- Status transitions are taken under a row lock (SELECT ... FOR UPDATE
-- SKIP LOCKED) so two workers cannot both claim one row.

CREATE TABLE notification_outbox (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    notification_id     UUID NOT NULL
                            REFERENCES notifications(id) ON DELETE CASCADE,

    channel             TEXT NOT NULL
                            CHECK (channel IN ('in_app', 'email')),

    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sent', 'failed',
                                              'suppressed', 'dead')),

    attempt_count       INT NOT NULL DEFAULT 0,

    -- The retry worker's claim predicate. Always set for `pending`;
    -- NULL once the row reaches a terminal state.
    next_attempt_at     TIMESTAMPTZ DEFAULT now(),

    last_error          TEXT NOT NULL DEFAULT '',

    -- Provider-side id (SMTP Message-ID). Lets an operator correlate a
    -- complaint with a specific send without reading the body.
    provider_message_id TEXT NOT NULL DEFAULT '',

    -- Why a `suppressed` row was suppressed: 'preference', 'quiet_hours',
    -- 'no_email_address', 'digest_deferred'. Empty for other statuses.
    suppressed_reason   TEXT NOT NULL DEFAULT '',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The delivery-idempotency anchor.
CREATE UNIQUE INDEX notification_outbox_channel_unique
    ON notification_outbox (notification_id, channel);

-- Drives the delivery/retry worker's claim query. Partial: terminal rows
-- are the overwhelming majority over time and must not be scanned.
CREATE INDEX notification_outbox_due_idx
    ON notification_outbox (next_attempt_at, id)
    WHERE status = 'pending';

-- Drives the DLQ reaper and the failure-rate alert.
CREATE INDEX notification_outbox_status_idx
    ON notification_outbox (tenant_id, status, updated_at DESC);

CREATE TRIGGER notification_outbox_set_updated_at
    BEFORE UPDATE ON notification_outbox
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_outbox FORCE  ROW LEVEL SECURITY;

CREATE POLICY notification_outbox_tenant_select ON notification_outbox
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_outbox_tenant_insert ON notification_outbox
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_outbox_tenant_update ON notification_outbox
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Delivery history is evidence. No app-level delete.
CREATE POLICY notification_outbox_tenant_delete ON notification_outbox
    FOR DELETE TO app_role
    USING (false);
CREATE POLICY notification_outbox_tenant_restrictive ON notification_outbox
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON notification_outbox TO app_role;

GRANT SELECT, INSERT, UPDATE ON notification_outbox TO app_notification_worker;
CREATE POLICY notification_outbox_worker_select ON notification_outbox
    FOR SELECT TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_outbox_worker_insert ON notification_outbox
    FOR INSERT TO app_notification_worker
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_outbox_worker_update ON notification_outbox
    FOR UPDATE TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_outbox_worker_restrictive ON notification_outbox
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── notification_digest_progress ────────────────────────────────────
-- Daily-digest idempotency marker. The marker is CLAIMED BEFORE the
-- work: the job INSERTs the marker first and treats a unique-violation
-- as "another worker owns this user-day", so the claim is atomic and a
-- concurrent runner can never double-send the same user's digest.

CREATE TABLE notification_digest_progress (
    digest_date             DATE NOT NULL,
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_id                 UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    -- Set when the claim is taken; the row exists before the send.
    claimed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set once the digest is actually sent. A row with claimed_at set but
    -- finished_at NULL and an old claim is a crashed run — the runbook's
    -- signal to investigate rather than blindly re-send.
    finished_at             TIMESTAMPTZ,

    notifications_included  INT NOT NULL DEFAULT 0,

    PRIMARY KEY (digest_date, tenant_id, user_id)
);

CREATE INDEX notification_digest_progress_unfinished_idx
    ON notification_digest_progress (digest_date, tenant_id)
    WHERE finished_at IS NULL;

ALTER TABLE notification_digest_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_digest_progress FORCE  ROW LEVEL SECURITY;

-- app_role gets INSERT/UPDATE as well as SELECT because the digest job
-- currently runs INSIDE notification-service, on the app_role pool.
-- No DELETE for either role: re-running a day must be a deliberate
-- operator action, not something the job can do to itself.
CREATE POLICY notification_digest_progress_tenant_select ON notification_digest_progress
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_tenant_insert ON notification_digest_progress
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_tenant_update ON notification_digest_progress
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_tenant_restrictive ON notification_digest_progress
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON notification_digest_progress TO app_role;

GRANT SELECT, INSERT, UPDATE ON notification_digest_progress TO app_notification_worker;
CREATE POLICY notification_digest_progress_worker_select ON notification_digest_progress
    FOR SELECT TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_worker_insert ON notification_digest_progress
    FOR INSERT TO app_notification_worker
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_worker_update ON notification_digest_progress
    FOR UPDATE TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notification_digest_progress_worker_restrictive ON notification_digest_progress
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- ── audit.notification_dead_letters ─────────────────────────────────
-- Forensic record for deliveries that exhausted their retries, and for
-- envelopes that could not be processed at all. Lives in `audit`
-- because it is evidence, not application state.
--
-- `tenant_id` is NULLABLE for exactly one case: an envelope so
-- malformed that the tenant could not be read off it. Discarding that
-- row would destroy the only evidence of a broken producer, so it is
-- written with a NULL tenant and is consequently invisible to every
-- tenant-scoped role — only an operator connecting as a superuser sees
-- it.

CREATE TABLE audit.notification_dead_letters (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- NULL only when the envelope could not be parsed. See above.
    tenant_id           UUID,

    -- Which axis died: 'ingest' (the envelope never materialised) or
    -- 'delivery' (the notification exists but a channel never sent).
    source              TEXT NOT NULL
                            CHECK (source IN ('ingest', 'delivery')),

    -- Set for source='delivery'. Deliberately NOT an FK: the whole point
    -- is to outlive the row it describes.
    notification_id     UUID,
    outbox_id           UUID,
    channel             TEXT NOT NULL DEFAULT ''
                            CHECK (channel IN ('', 'in_app', 'email')),

    -- Set for source='ingest': the producer's idempotency seed, so a
    -- forensic replay can be de-duplicated against what did materialise.
    event_id            UUID,

    attempt_count       INT NOT NULL DEFAULT 0,
    last_error          TEXT NOT NULL DEFAULT '',

    -- The full envelope, verbatim, for replay. Content-free by the same
    -- construction as the envelope itself (scalar-only payload, enforced
    -- in libs/notification_events).
    envelope            JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Drives the "DLQ non-empty" alert and the operator's triage view.
CREATE INDEX notification_dead_letters_recent_idx
    ON audit.notification_dead_letters (created_at DESC);
CREATE INDEX notification_dead_letters_tenant_idx
    ON audit.notification_dead_letters (tenant_id, created_at DESC)
    WHERE tenant_id IS NOT NULL;

ALTER TABLE audit.notification_dead_letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.notification_dead_letters FORCE  ROW LEVEL SECURITY;

-- Tenant-scoped read for support tooling. NULL-tenant rows match no
-- tenant and are therefore operator-only, by design.
CREATE POLICY notification_dead_letters_tenant_select
    ON audit.notification_dead_letters
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- The NULL-tenant case is the unparseable envelope: it is written on a
-- pool connection with no tenant scope set, so the predicate must admit
-- it or the evidence is lost.
CREATE POLICY notification_dead_letters_tenant_insert
    ON audit.notification_dead_letters
    FOR INSERT TO app_role
    WITH CHECK (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );
CREATE POLICY notification_dead_letters_tenant_restrictive
    ON audit.notification_dead_letters
    AS RESTRICTIVE FOR ALL TO app_role
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );

-- app_role writes here too: the ingest consumer and the delivery worker
-- both run inside notification-service on the app_role pool, and a
-- dead-letter that cannot be written is evidence destroyed at exactly
-- the moment it is needed. INSERT only. Nothing may UPDATE or DELETE a
-- forensic row. Table grants are inert without schema USAGE; app_role
-- does not otherwise reach into `audit` (audit.events is the
-- audit_writer role's alone), so it has to be granted explicitly here.
GRANT USAGE ON SCHEMA audit TO app_role;
GRANT SELECT, INSERT ON audit.notification_dead_letters TO app_role;
GRANT USAGE ON SCHEMA audit TO app_notification_worker;
GRANT SELECT, INSERT ON audit.notification_dead_letters TO app_notification_worker;

CREATE POLICY notification_dead_letters_worker_select
    ON audit.notification_dead_letters
    FOR SELECT TO app_notification_worker
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );
CREATE POLICY notification_dead_letters_worker_insert
    ON audit.notification_dead_letters
    FOR INSERT TO app_notification_worker
    WITH CHECK (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );
CREATE POLICY notification_dead_letters_worker_restrictive
    ON audit.notification_dead_letters
    AS RESTRICTIVE FOR ALL TO app_notification_worker
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)::uuid
    );

-- ── Tenant enumeration for the background workers ───────────────────
-- The delivery worker and the digest job both need to answer "which
-- tenants have work?" BEFORE they can open a tenant-scoped connection —
-- an inherently cross-tenant question. Asked on a plain app_role
-- connection it fails in two ways, the quiet one worse: the RLS
-- predicate either raises on the unset setting, or silently filters
-- every row out and the job "succeeds" doing nothing. SECURITY DEFINER
-- functions are the sanctioned answer; both return nothing but tenant
-- ids.

CREATE OR REPLACE FUNCTION notification_tenants_with_due_outbox()
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
-- Pinned search_path: a SECURITY DEFINER function without one is a
-- privilege-escalation vector.
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT o.tenant_id
      FROM notification_outbox o
     WHERE o.status = 'pending'
       AND o.next_attempt_at <= now();
$$;

CREATE OR REPLACE FUNCTION notification_active_tenant_ids()
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT t.id FROM tenants t WHERE t.is_active = true;
$$;

REVOKE ALL ON FUNCTION notification_tenants_with_due_outbox() FROM PUBLIC;
REVOKE ALL ON FUNCTION notification_active_tenant_ids() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION notification_tenants_with_due_outbox() TO app_role;
GRANT EXECUTE ON FUNCTION notification_active_tenant_ids() TO app_role;
GRANT EXECUTE ON FUNCTION notification_tenants_with_due_outbox() TO app_notification_worker;
GRANT EXECUTE ON FUNCTION notification_active_tenant_ids() TO app_notification_worker;
