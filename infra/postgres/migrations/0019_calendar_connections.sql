-- 0019 — Calendar connections (Google Calendar, read-only).
--
-- The home page's "Coming up" list needs the user's next meetings, on
-- every client at once — the web app has no local calendar to read, and
-- the Mac app's EventKit list only knows the accounts added to that Mac.
-- So the connection lives on the server: one row per (user, provider,
-- account), holding the OAuth tokens Google handed us.
--
-- Tokens are the sensitive part. They are enveloped with the tenant's KEK
-- (libs/crypto, ADR-0011) before they touch the row: `token_blob` is the
-- serialized envelope (header + ciphertext), never plaintext. A database
-- dump yields nothing without the master key.
--
-- A connection belongs to ONE user: RLS scopes rows to the tenant, and the
-- service filters on `user_sub` on top — a colleague never sees your
-- calendar. Disconnecting revokes the token at Google and stamps
-- `revoked_at`; the row stays for the audit trail (hard DELETE is
-- forbidden by policy, as everywhere else).
--
-- `hidden_calendar_ids` lists the calendars the user switched OFF in the
-- picker (empty = every calendar of the account feeds the list). Hidden
-- rather than chosen so a calendar that appears later shows up by
-- default, which is what people expect.

CREATE TABLE calendar_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    user_sub            UUID NOT NULL,
    provider            TEXT NOT NULL CHECK (provider IN ('google')),
    account_email       TEXT NOT NULL,
    -- Enveloped JSON {access_token, refresh_token}; see note above.
    token_blob          BYTEA NOT NULL,
    token_expires_at    TIMESTAMPTZ,
    scopes              TEXT[] NOT NULL DEFAULT '{}',
    hidden_calendar_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    -- Set when Google refused a refresh (token revoked from the Google
    -- side, password changed): the client shows "Sign in again".
    needs_reauth        BOOLEAN NOT NULL DEFAULT false,
    last_synced_at      TIMESTAMPTZ,
    -- Short machine-readable reason of the last failed sync, for support.
    last_error          TEXT
);

-- One LIVE connection per account; revoked ones stay as history.
CREATE UNIQUE INDEX calendar_connections_live_idx
    ON calendar_connections (tenant_id, user_sub, provider, account_email)
    WHERE revoked_at IS NULL;

CREATE INDEX calendar_connections_user_idx
    ON calendar_connections (tenant_id, user_sub)
    WHERE revoked_at IS NULL;

ALTER TABLE calendar_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_connections FORCE  ROW LEVEL SECURITY;

CREATE POLICY calendar_connections_tenant_select ON calendar_connections
    FOR SELECT TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY calendar_connections_tenant_insert ON calendar_connections
    FOR INSERT TO app_role
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY calendar_connections_tenant_update ON calendar_connections
    FOR UPDATE TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY calendar_connections_tenant_delete ON calendar_connections
    FOR DELETE TO app_role
    USING (false);  -- revocation is the delete

CREATE POLICY calendar_connections_tenant_restrictive ON calendar_connections
    AS RESTRICTIVE
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON calendar_connections TO app_role;
