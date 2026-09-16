-- 0024 — the native-IdP data model: `identities`, `auth_challenges`,
-- `auth_sessions`, `tenants.kind`, and the platform tenant.
--
-- Scope note (IDX-A3): the identity pack puts these tables in IDX-A1.
-- A1 has not been run, and A3's route layer cannot exist without them,
-- so this migration carries the *minimum* A1 slice email-code sign-in
-- needs. A1 proper extends it (external identity providers, per-identity
-- settings, deletion tombstones); nothing here forecloses that.
--
-- ── Why these three tables are NOT tenant-scoped ────────────────────
-- Every other table in this schema hangs off `tenants(id)` and is filtered
-- by `app.tenant_id` under RLS. These cannot be: an identity exists before
-- it has a workspace (that is the whole point of self-serve signup), an
-- `auth_challenges` row is created for an address that may belong to
-- nobody, and a session is the thing that *decides* which tenant the
-- caller is in. Scoping them to a tenant would be circular.
--
-- The isolation they get instead is role isolation: `tenant_writer`
-- (auth-service, and only auth-service) can touch them; `app_role` — the
-- role every other service in the fleet connects as — is granted nothing
-- at all. RLS is still ENABLEd and FORCEd with a writer-only policy, so
-- if a later migration hands `app_role` a table grant by accident, the
-- absence of a policy still denies every row.

-- ── tenants.kind ────────────────────────────────────────────────────
-- A personal workspace is created by signup and owned by exactly one
-- identity; a team workspace is onboarded (B1 invites people into it).
-- `platform` is the single home for audit events that belong to no
-- customer — an OTP request for an address nobody has ever registered.
--
-- DEFAULT 'team' backfills every existing row, which is correct: every
-- tenant that exists today was onboarded, not self-served.
ALTER TABLE tenants
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'team'
        CHECK (kind IN ('personal', 'team', 'platform'));

CREATE INDEX tenants_kind_idx ON tenants (kind);

-- The platform tenant. Pinned UUID so `AUTH_PLATFORM_TENANT_ID` has a
-- working default in dev and in every test database, and so the audit
-- trail for pre-account events is the same row everywhere.
INSERT INTO tenants (id, name, display_name, kind, locale, timezone, status)
VALUES ('00000000-0000-0000-0000-0000000000f1', 'platform', 'Klarnote Platform',
        'platform', 'en', 'UTC', 'active')
ON CONFLICT (id) DO NOTHING;


-- ── identities ──────────────────────────────────────────────────────
-- One row per person, keyed by the address they prove control of. This is
-- the `sub` of every native token, and the `user_sub` of the memberships
-- that decide which workspaces they can reach.

CREATE TABLE identities (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Stored already normalised. The CHECK is the invariant the uniqueness
    -- depends on: "Ada@Example.com" and "ada@example.com" must not be two
    -- accounts, and a case-folding bug in one caller would silently make
    -- them two without it.
    email             TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    email_verified_at TIMESTAMPTZ,
    display_name      TEXT NOT NULL DEFAULT '',

    -- active          — normal.
    -- pending_deletion— inside the deletion grace window; signing in
    --                   reactivates (IDX-A3 F3, the documented behaviour).
    -- deleted         — purged; the address was rewritten, so a login
    --                   lookup can never match one. Kept as a tombstone.
    -- disabled        — turned off by an operator; 403 account_disabled.
    status            TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'pending_deletion',
                                            'deleted', 'disabled')),

    mfa_enabled       BOOLEAN NOT NULL DEFAULT false,

    -- IDX-A4 owns every write to this column. A3 only reads whether it is
    -- NULL, to answer `has_password` in AuthResult — a client needs to know
    -- whether to offer "sign in with a password" next time.
    password_hash     TEXT,

    -- Where a returning sign-in lands. NULL for a brand-new identity until
    -- its personal workspace exists.
    last_tenant_id    UUID REFERENCES tenants(id) ON DELETE SET NULL,

    -- ── lockout (IDX-A3 F5) ──────────────────────────────────────────
    -- Deliberately in Postgres, not Redis: the brute-force control this
    -- replaces (Keycloak's) survived cache restarts, and a lockout that
    -- forgets everything when Redis blinks is not a lockout.
    failed_login_count INT NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    -- How many times this account has been locked. Drives the doubling.
    lock_count         INT NOT NULL DEFAULT 0 CHECK (lock_count >= 0),
    locked_until       TIMESTAMPTZ,
    -- When the "temporarily locked" mail for the CURRENT lock went out, so
    -- an attacker cannot turn the lockout into a mail cannon aimed at the
    -- victim: one notice per lock, not one per attempt.
    lock_notified_at   TIMESTAMPTZ,

    deletion_requested_at TIMESTAMPTZ,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX identities_locked_idx ON identities (locked_until)
    WHERE locked_until IS NOT NULL;

CREATE TRIGGER identities_set_updated_at
    BEFORE UPDATE ON identities
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

GRANT SELECT, INSERT, UPDATE ON identities TO tenant_writer;

ALTER TABLE identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE identities FORCE  ROW LEVEL SECURITY;

CREATE POLICY identities_writer_all ON identities
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);


-- ── auth_challenges ─────────────────────────────────────────────────
-- One row per code issued. The code itself is never here: `code_hash` is
-- sha256("<code>:<id>"), bound to the row's own id, so a hash lifted from
-- a backup cannot be replayed against a different challenge.

CREATE TABLE auth_challenges (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 'email_login' today. A5 adds 'mfa_totp'; B1 adds 'invite'.
    kind         TEXT NOT NULL
                     CHECK (kind IN ('email_login', 'mfa_totp', 'invite')),

    -- The address the code was mailed to, normalised. NOT an FK to
    -- identities: the whole signup path is a challenge for an address that
    -- has no identity yet.
    email        TEXT NOT NULL CHECK (email = lower(email)),
    identity_id  UUID REFERENCES identities(id) ON DELETE CASCADE,

    code_hash    TEXT NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,

    attempts     INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INT NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    -- Set when the code is spent, when the attempt budget runs out, or
    -- when a newer challenge for the same address supersedes it. A row
    -- with a non-NULL value here is inert for every purpose.
    consumed_at  TIMESTAMPTZ,

    client_type  TEXT NOT NULL DEFAULT 'web',
    ip           TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "Supersede the open challenges for this address" — the hot path of
-- every /auth/email/start.
CREATE INDEX auth_challenges_open_idx
    ON auth_challenges (email, kind)
    WHERE consumed_at IS NULL;

-- The B3 purge sweep ("delete challenges 24 h past expiry").
CREATE INDEX auth_challenges_expiry_idx ON auth_challenges (expires_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON auth_challenges TO tenant_writer;

ALTER TABLE auth_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_challenges FORCE  ROW LEVEL SECURITY;

CREATE POLICY auth_challenges_writer_all ON auth_challenges
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);


-- ── auth_sessions ───────────────────────────────────────────────────
-- The row behind a native token's `sid`. A3 only creates them (every
-- successful verify starts a NEW one — no session fixation); the rest of
-- IDX-A2 adds rotation, tenant switching and revocation on top.

CREATE TABLE auth_sessions (
    -- This is the `sid` claim.
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id        UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    -- The workspace this session is currently scoped to (the `tid` claim).
    tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,

    -- sha256 of the refresh token. The token itself is shown to the client
    -- exactly once and never stored, exactly like the password-reset token.
    refresh_token_hash BYTEA NOT NULL UNIQUE,

    client_type        TEXT NOT NULL DEFAULT 'web',
    ip                 TEXT NOT NULL DEFAULT '',
    user_agent         TEXT NOT NULL DEFAULT '',
    mfa                BOOLEAN NOT NULL DEFAULT false,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ
);

CREATE INDEX auth_sessions_identity_idx ON auth_sessions (identity_id)
    WHERE revoked_at IS NULL;
CREATE INDEX auth_sessions_expiry_idx ON auth_sessions (expires_at);

GRANT SELECT, INSERT, UPDATE ON auth_sessions TO tenant_writer;

ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions FORCE  ROW LEVEL SECURITY;

CREATE POLICY auth_sessions_writer_all ON auth_sessions
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);
