-- 0012 — password recovery (forgot/reset, change, "that wasn't me")
--         and the standing MFA-reminder finding.
--
-- Password recovery has three independent halves:
--
--   auth_password_reset_tokens — THE CREDENTIAL. A single-use,
--       short-lived opaque token, stored only as sha256. Two purposes
--       share the table because they share every rule (single-use,
--       expiring, hashed, swept): `password_reset` is the link in the
--       "forgot password" mail, `account_lockdown` is the link in the
--       security notification that lets a user who did NOT change their
--       password kill every live session and retake the account.
--
--   auth_mail_outbox — THE MAIL. Enqueued in the same transaction that
--       mints the token, drained by a background worker. Sending inline
--       would hold the DB transaction that holds the token row through a
--       30-second SMTP stall, and a failed send would lose a mail the
--       user is actively waiting for.
--
--   auth_password_events — THE TRAIL, denormalised for the "recent
--       security activity" list the SPA settings page renders. The audit
--       chain remains the authority; this is a queryable projection that
--       does not require audit.read.
--
-- Deliberately NOT modelled: password history / reuse prevention. NIST
-- SP 800-63B explicitly recommends against forced rotation and reuse
-- rules, and storing prior hashes would mean holding more verifiers
-- than Keycloak already does. Strength is checked at set time instead.

-- ── Reset / lockdown tokens ─────────────────────────────────────────

CREATE TABLE auth_password_reset_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- Whose account the token acts on. CASCADE because a deleted user's
    -- pending reset link must die with them.
    subject_sub     UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    -- sha256 of the opaque token. The plaintext exists only in the mail
    -- body and (briefly) in auth_mail_outbox.secret_fields; a database
    -- read yields nothing redeemable.
    token_hash      BYTEA NOT NULL,

    purpose         TEXT NOT NULL
                        CHECK (purpose IN ('password_reset', 'account_lockdown')),

    -- Salted hash of the requesting IP, for abuse forensics. Never the
    -- raw address: a raw IP is personal data under GDPR.
    requested_ip_hash TEXT NOT NULL DEFAULT '',

    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,

    CONSTRAINT auth_password_reset_window_is_forward
        CHECK (expires_at > issued_at)
);

-- Global uniqueness (not per-tenant): the hash is 256 bits of CSPRNG
-- output, and redemption looks the token up BEFORE any tenant is known.
CREATE UNIQUE INDEX auth_password_reset_tokens_hash_unique
    ON auth_password_reset_tokens (token_hash);
CREATE INDEX auth_password_reset_tokens_expiry_idx
    ON auth_password_reset_tokens (expires_at)
    WHERE consumed_at IS NULL;
-- Drives "invalidate every outstanding token for this user", which both
-- a completed reset and a lockdown must do.
CREATE INDEX auth_password_reset_tokens_subject_idx
    ON auth_password_reset_tokens (subject_sub)
    WHERE consumed_at IS NULL;

ALTER TABLE auth_password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_password_reset_tokens FORCE  ROW LEVEL SECURITY;

CREATE POLICY auth_password_reset_tokens_tenant_select ON auth_password_reset_tokens
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_password_reset_tokens_tenant_insert ON auth_password_reset_tokens
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_password_reset_tokens_tenant_update ON auth_password_reset_tokens
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_password_reset_tokens_tenant_delete ON auth_password_reset_tokens
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_password_reset_tokens_tenant_restrictive ON auth_password_reset_tokens
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON auth_password_reset_tokens TO app_role;

-- ── Outbound mail ───────────────────────────────────────────────────

CREATE TABLE auth_mail_outbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    subject_sub     UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    kind            TEXT NOT NULL
                        CHECK (kind IN ('password_reset', 'password_changed')),
    lang            TEXT NOT NULL DEFAULT 'en'
                        CHECK (lang IN ('en', 'de', 'uk')),
    to_address      TEXT NOT NULL,

    -- Everything the template needs that is NOT a credential: display
    -- name, timestamps, the user-agent summary, the support URL.
    -- Retained for the life of the row so a delivery question can be
    -- answered.
    render_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- The token-bearing variables (reset_url, lockdown_url), split out
    -- so they can be destroyed the moment they stop being needed —
    -- otherwise this table becomes a store of live credentials with no
    -- TTL. The CHECK below makes the clearing an invariant rather than
    -- a habit the worker has to remember.
    secret_fields   JSONB,

    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'dead')),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error      TEXT NOT NULL DEFAULT '',
    provider_message_id TEXT NOT NULL DEFAULT '',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ,

    -- A row that is no longer pending must carry no redeemable secret.
    CONSTRAINT auth_mail_outbox_secrets_cleared
        CHECK (status = 'pending' OR secret_fields IS NULL)
);

CREATE INDEX auth_mail_outbox_due_idx
    ON auth_mail_outbox (next_attempt_at)
    WHERE status = 'pending';
CREATE INDEX auth_mail_outbox_subject_idx
    ON auth_mail_outbox (subject_sub, created_at DESC);

ALTER TABLE auth_mail_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_mail_outbox FORCE  ROW LEVEL SECURITY;

CREATE POLICY auth_mail_outbox_tenant_select ON auth_mail_outbox
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_mail_outbox_tenant_insert ON auth_mail_outbox
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_mail_outbox_tenant_update ON auth_mail_outbox
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_mail_outbox_tenant_delete ON auth_mail_outbox
    FOR DELETE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_mail_outbox_tenant_restrictive ON auth_mail_outbox
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON auth_mail_outbox TO app_role;

-- ── Security-activity projection ────────────────────────────────────

CREATE TABLE auth_password_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    subject_sub     UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    kind            TEXT NOT NULL CHECK (kind IN (
                        'reset_requested',
                        'reset_completed',
                        'password_changed',
                        'lockdown_triggered'
                    )),
    -- 'self' when the account holder acted, 'reset_link' when a mailed
    -- token did, 'admin' for an operator-driven change. Answers "how did
    -- this password change" without joining the audit chain.
    via             TEXT NOT NULL DEFAULT 'self'
                        CHECK (via IN ('self', 'reset_link', 'admin')),

    ip_hash         TEXT NOT NULL DEFAULT '',
    -- Coarse client description ("Chrome on macOS"), never the raw UA.
    client_label    TEXT NOT NULL DEFAULT '',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX auth_password_events_subject_idx
    ON auth_password_events (subject_sub, created_at DESC);

ALTER TABLE auth_password_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_password_events FORCE  ROW LEVEL SECURITY;

CREATE POLICY auth_password_events_tenant_select ON auth_password_events
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY auth_password_events_tenant_insert ON auth_password_events
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- The trail is evidence. Nothing edits or deletes it.
CREATE POLICY auth_password_events_tenant_update ON auth_password_events
    FOR UPDATE TO app_role
    USING (false);
CREATE POLICY auth_password_events_tenant_delete ON auth_password_events
    FOR DELETE TO app_role
    USING (false);
CREATE POLICY auth_password_events_tenant_restrictive ON auth_password_events
    AS RESTRICTIVE FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON auth_password_events TO app_role;

-- ── Tenant-blind token redemption ───────────────────────────────────
-- Redemption starts from a token and nothing else: the browser
-- following a link from an email carries no session and no tenant. RLS
-- needs `app.tenant_id` set BEFORE the query, so the lookup cannot be
-- an ordinary SELECT — a SECURITY DEFINER function with a single,
-- narrow job is the sanctioned answer.
--
-- The function claims the token atomically (the UPDATE ... WHERE
-- consumed_at IS NULL is the compare-and-swap), so two concurrent
-- redemptions of the same link cannot both win. It returns the tenant
-- and subject the caller then scopes every subsequent statement to.
-- It reveals nothing about tokens that do not exist, are spent, or have
-- expired: all three return zero rows.

CREATE OR REPLACE FUNCTION public.consume_password_reset_token(
    p_token_hash BYTEA,
    p_purpose    TEXT
)
RETURNS TABLE (tenant_id UUID, subject_sub UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    UPDATE auth_password_reset_tokens
       SET consumed_at = now()
     WHERE token_hash = p_token_hash
       AND purpose    = p_purpose
       AND consumed_at IS NULL
       AND expires_at  > now()
    RETURNING tenant_id, subject_sub;
$$;

REVOKE ALL ON FUNCTION public.consume_password_reset_token(BYTEA, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.consume_password_reset_token(BYTEA, TEXT) TO app_role;

-- Look at a token WITHOUT spending it.
--
-- The reset handler needs the account behind a token before it can
-- judge the proposed password (the policy refuses a password containing
-- the user's own email or name). Consuming first and validating second
-- would burn a legitimate user's one-use link on a weak-password typo
-- while buying nothing against an attacker (who submits a strong
-- password and wins on the first attempt). So: peek, judge, and only
-- then consume. The window between the peek and the consume is harmless
-- because the consume is still an atomic compare-and-swap.

CREATE OR REPLACE FUNCTION public.peek_password_reset_token(
    p_token_hash BYTEA,
    p_purpose    TEXT
)
RETURNS TABLE (tenant_id UUID, subject_sub UUID)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT t.tenant_id, t.subject_sub
      FROM auth_password_reset_tokens t
     WHERE t.token_hash = p_token_hash
       AND t.purpose    = p_purpose
       AND t.consumed_at IS NULL
       AND t.expires_at  > now();
$$;

REVOKE ALL ON FUNCTION public.peek_password_reset_token(BYTEA, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.peek_password_reset_token(BYTEA, TEXT) TO app_role;

-- The mirror of the above for the request side: resolve an email to
-- (tenant, sub, display name, status) without a tenant already in hand.
-- `users.email` is unique per tenant rather than globally, so the
-- deterministic ordering picks the oldest active match. Returning the
-- status lets the caller decline to mail a deactivated account while
-- still answering the HTTP request identically.

CREATE OR REPLACE FUNCTION public.resolve_account_for_password_reset(
    p_email TEXT
)
RETURNS TABLE (
    tenant_id    UUID,
    subject_sub  UUID,
    email        TEXT,
    display_name TEXT,
    status       TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT u.tenant_id, u.sub, u.email, COALESCE(u.display_name, ''), u.status
      FROM users u
     WHERE lower(u.email) = lower(p_email)
     ORDER BY (u.status = 'active') DESC, u.created_at
     LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.resolve_account_for_password_reset(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.resolve_account_for_password_reset(TEXT) TO app_role;

-- Which tenants currently have deliverable mail. The outbox drain is a
-- background loop with no tenant of its own; it asks this first, then
-- opens a properly scoped connection per tenant to do the actual work —
-- so the only thing that crosses the tenancy boundary is a list of
-- tenant ids, not a single row of anybody's mail.

CREATE OR REPLACE FUNCTION public.tenants_with_due_auth_mail(
    p_limit INTEGER DEFAULT 100
)
RETURNS TABLE (tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT o.tenant_id
      FROM auth_mail_outbox o
     WHERE o.status = 'pending' AND o.next_attempt_at <= now()
     LIMIT p_limit;
$$;

REVOKE ALL ON FUNCTION public.tenants_with_due_auth_mail(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tenants_with_due_auth_mail(INTEGER) TO app_role;

-- ── mfa_reminders ───────────────────────────────────────────────────
-- An oversight role asking a user to turn MFA on. The access review
-- shows an auditor who holds a second factor and who does not; the one
-- action the auditor gets is to raise a STANDING request that the user
-- enrols. A notification is a moment; a finding stays open until it is
-- closed. One row per (tenant, user) holds the open request, and it
-- closes exactly one way: the user enrols, and `POST /auth/mfa/verify`
-- stamps `resolved_at`. There is no dismiss button anywhere in the
-- product, because a reminder a user can wave away is a reminder that
-- measures nothing. Re-reminding bumps `reminder_count` and
-- `last_reminded_at` on the SAME row — the count is the escalation
-- record an auditor shows when the finding is still open three reviews
-- later.
--
-- The row is also read by the *subject*: `GET /auth/me` returns the
-- open reminder so the SPA can carry a banner until enrolment.

CREATE TABLE mfa_reminders (
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- Who was asked. CASCADE: the reminder is about an account, and an
    -- account that no longer exists has no open finding.
    subject_sub     UUID NOT NULL REFERENCES users(sub) ON DELETE CASCADE,

    -- Who asked. Nullable + SET NULL rather than CASCADE: the reminder
    -- outlives the reviewer who raised it. Deleting the auditor must not
    -- silently close a finding on somebody else's account.
    requested_by    UUID REFERENCES users(sub) ON DELETE SET NULL,
    -- Denormalised so the subject's banner can say "your workspace
    -- administrator" vs "an auditor" without a join the subject is not
    -- allowed to make, and so it survives `requested_by` going NULL.
    requested_by_role TEXT NOT NULL
                        CHECK (requested_by_role IN ('tenant_admin', 'auditor')),

    first_reminded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reminded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reminder_count    INTEGER NOT NULL DEFAULT 1 CHECK (reminder_count > 0),

    -- NULL ⇒ open. Stamped by MFA enrolment, never by the user
    -- dismissing anything. Kept (rather than the row deleted) so the
    -- review history reads "asked twice, enrolled on the 4th" instead
    -- of going blank.
    resolved_at       TIMESTAMPTZ,

    PRIMARY KEY (tenant_id, subject_sub)
);

-- The roster join reads open reminders for a page of users at a time.
CREATE INDEX mfa_reminders_open_idx
    ON mfa_reminders (tenant_id, subject_sub)
    WHERE resolved_at IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_reminders TO app_role, tenant_writer;

ALTER TABLE mfa_reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE mfa_reminders FORCE  ROW LEVEL SECURITY;

CREATE POLICY mfa_reminders_app_role_tenant ON mfa_reminders
    FOR ALL TO app_role
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY mfa_reminders_writer_tenant ON mfa_reminders
    FOR ALL TO tenant_writer
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- RESTRICTIVE: defence in depth, same shape as `users`.
CREATE POLICY mfa_reminders_tenant_restrictive ON mfa_reminders
    AS RESTRICTIVE FOR ALL
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
