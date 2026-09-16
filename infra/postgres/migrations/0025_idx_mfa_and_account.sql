-- 0025 — IDX-A5: second factors, session bookkeeping, and the columns the
-- account surface (email change, deletion, profile) writes.
--
-- Same doctrine as 0024: none of these tables has a `tenant_id`, because a
-- second factor belongs to an identity and an identity exists before it has
-- a workspace. Isolation is the role grant plus a `tenant_writer`-only RLS
-- policy; `app_role` — what the rest of the fleet connects as — is granted
-- nothing and has no policy, so it fails closed twice.

-- ── auth_challenges: more kinds, and a place to park context ─────────
--
-- A5 adds three flows that are all "prove something with a short-lived
-- code", which is exactly what this table already is:
--
--   totp_enroll  — holds the candidate secret until a code confirms it, so
--                  a half-finished enrolment never locks anyone out.
--   mfa_login    — the gap between a passed first factor and a session. It
--                  carries the first factor's context (client type, IP, the
--                  workspace that was asked for) so the session that is
--                  eventually started is the one that was requested, not
--                  one shaped by wherever the second factor came from.
--   email_change — the code sent to the NEW address, and (a second row) the
--                  24 h revert token sent to the old one.
--   reauth       — the step-up code for an identity that has no second
--                  factor and, until IDX-A4, no password either.
ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_kind_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_kind_check
    CHECK (kind IN ('email_login', 'mfa_totp', 'invite',
                    'totp_enroll', 'mfa_login', 'email_change', 'reauth'));

-- Flow-specific context. Never a secret: the candidate TOTP secret goes in
-- `identity_totp.secret_enc` (envelope-encrypted) and the revert token is
-- hashed into `code_hash` like every other code. What lives here is the
-- kind of thing that would otherwise need a column per flow — the first
-- factor's client type, the workspace it asked for, the address being
-- replaced.
ALTER TABLE auth_challenges
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- `email` is the address a code is SENT to, and for `email_change` that is
-- the new one. The 0024 CHECK (email = lower(email)) still holds.

-- ── auth_sessions: what the sessions screen and step-up need ────────
--
-- `last_authenticated_at` is the whole "recent auth" mechanism: a first
-- factor or a successful /auth/reauth stamps it, and the endpoints that
-- can lock someone out of their own account (disable MFA, change email,
-- delete the account) refuse to act on a session that has not proved
-- itself recently. A stolen laptop with a warm session is the threat; an
-- access token alone must not be enough to take the account away.
ALTER TABLE auth_sessions
    ADD COLUMN last_authenticated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Shown in the sessions list so a person can recognise their own devices
-- ("MacBook Pro", "iPhone"). Derived from the user agent, never trusted
-- for anything but display.
ALTER TABLE auth_sessions
    ADD COLUMN device_name TEXT NOT NULL DEFAULT '';

-- Why a session ended. Read by the audit trail and the security-events
-- list; `NULL` while the session is live.
ALTER TABLE auth_sessions
    ADD COLUMN revoked_reason TEXT
        CHECK (revoked_reason IS NULL OR revoked_reason IN
               ('logout', 'user_revoked', 'revoke_others', 'mfa_change',
                'password_change', 'email_change', 'email_reverted',
                'account_deleted', 'admin', 'replay'));

-- ── identities: the profile columns PATCH /auth/me writes ───────────
--
-- Today these live on `users` (per-tenant). An identity spans workspaces,
-- so the language someone reads mail in belongs to the person, not to one
-- of their workspaces. `users` keeps its copies until IDX-B2 retires it.
ALTER TABLE identities ADD COLUMN locale   TEXT NOT NULL DEFAULT 'en';
ALTER TABLE identities ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC';


-- ── identity_totp ───────────────────────────────────────────────────
-- One confirmed secret per identity. The secret is never stored in the
-- clear: `secret_enc` is a packed libs/crypto envelope (AES-256-GCM under
-- a DEK, wrapped by a tenant KEK, wrapped by the environment master key),
-- with the AAD binding it to this identity — a blob lifted from a backup
-- and pasted onto another row fails to decrypt.

CREATE TABLE identity_totp (
    identity_id    UUID PRIMARY KEY REFERENCES identities(id) ON DELETE CASCADE,

    secret_enc     TEXT NOT NULL,
    -- Which tenant's KEK wraps the DEK. Identity secrets use the platform
    -- tenant (an identity has no tenant of its own), recorded per row so a
    -- future re-keying knows what it is looking at without guessing.
    kek_tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- NULL until a code proves the authenticator was set up correctly.
    -- An unconfirmed row is not a second factor and must not gate a login.
    confirmed_at   TIMESTAMPTZ,

    -- The last time step a code was accepted for. RFC 6238 §5.2 lets a
    -- code stay valid across a drift window, which without this would let
    -- the same six digits be replayed for up to 90 seconds — long enough
    -- for someone reading over a shoulder.
    last_used_step BIGINT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER identity_totp_set_updated_at
    BEFORE UPDATE ON identity_totp
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON identity_totp TO tenant_writer;

ALTER TABLE identity_totp ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity_totp FORCE  ROW LEVEL SECURITY;

CREATE POLICY identity_totp_writer_all ON identity_totp
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);


-- ── identity_recovery_codes ─────────────────────────────────────────
-- Ten single-use codes, stored only as sha256. They are the answer to
-- "I lost my phone", so they are the one credential a user is told to
-- write down — and the one an attacker would most like to read out of a
-- database dump.

CREATE TABLE identity_recovery_codes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    code_hash   BYTEA NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Two identical codes for one identity would make "mark this one used"
    -- ambiguous. Generation retries on collision rather than tolerating it.
    UNIQUE (identity_id, code_hash)
);

-- "How many are left" and "is this code one of the unused ones" are the
-- only two questions ever asked of this table.
CREATE INDEX identity_recovery_codes_unused_idx
    ON identity_recovery_codes (identity_id)
    WHERE used_at IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON identity_recovery_codes TO tenant_writer;

ALTER TABLE identity_recovery_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity_recovery_codes FORCE  ROW LEVEL SECURITY;

CREATE POLICY identity_recovery_codes_writer_all ON identity_recovery_codes
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);
