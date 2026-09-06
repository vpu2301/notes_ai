-- IDX-M1 (carrying IDX-A2's remaining session half) — refresh-token rotation.
--
-- IDX-A3 created `auth_sessions` and could only ever INSERT into it:
-- `SessionService` had `start` and nothing else, so a native session was
-- born, lived for one access-token lifetime, and could not be renewed.
-- Rotation is what makes a stored refresh token worth storing, and it is
-- what IDX-M1's Keychain session on macOS is built on.
--
-- ── Why a second hash column ─────────────────────────────────────────
-- Rotation without a grace window turns every lost response into a
-- forced sign-out: the client sent its token, the server rotated it, the
-- reply never arrived (a sleeping laptop, a dropped Wi-Fi association),
-- and the client's next attempt presents a token the server has already
-- retired. Indistinguishable, at that point, from a stolen one.
--
-- So the previous hash is kept for `AUTH_REFRESH_GRACE_SECONDS` after the
-- rotation that retired it. Inside that window the presentation is a
-- retry and is answered with a fresh token; outside it, the same
-- presentation is a replay — the token was used twice, minutes apart,
-- which is what a stolen refresh token looks like — and the session is
-- revoked with `auth_refresh_replay` (docs/api/error-codes.md).
--
-- `rotated_at` is deliberately NOT re-stamped by a grace-window retry:
-- the window is measured from the rotation that retired the token, so a
-- caller replaying one token cannot keep extending its own grace.

ALTER TABLE auth_sessions
    ADD COLUMN previous_refresh_token_hash BYTEA,
    ADD COLUMN rotated_at TIMESTAMPTZ;

-- The lookup on the grace path, and the same uniqueness the current hash
-- has: one token, at most one session, whichever generation it belongs to.
CREATE UNIQUE INDEX auth_sessions_prev_refresh_idx
    ON auth_sessions (previous_refresh_token_hash)
    WHERE previous_refresh_token_hash IS NOT NULL;

COMMENT ON COLUMN auth_sessions.previous_refresh_token_hash IS
    'sha256 of the refresh token retired by the last rotation; valid for AUTH_REFRESH_GRACE_SECONDS after rotated_at, a replay after it.';
COMMENT ON COLUMN auth_sessions.rotated_at IS
    'When the current refresh token was issued. Not re-stamped by a grace-window retry.';

-- ── two more reasons a session can end ───────────────────────────────
-- `revoked_reason` (0025) is a closed set, and rotation adds two ways a
-- session dies that nobody could end deliberately: the account behind it
-- stopped being active, and the membership that scoped it to a workspace
-- was removed. Both are discovered *by* a refresh, which is why they
-- arrive with this migration and not with 0025.
--
-- `replay` is deliberately NOT renamed: 0025 already named it, and the
-- house rule is that the existing name wins — a rename would split one
-- account's session history across two words.
ALTER TABLE auth_sessions DROP CONSTRAINT auth_sessions_revoked_reason_check;

ALTER TABLE auth_sessions
    ADD CONSTRAINT auth_sessions_revoked_reason_check
    CHECK (revoked_reason IS NULL OR revoked_reason IN
        ('logout', 'user_revoked', 'revoke_others', 'mfa_change',
         'password_change', 'email_change', 'email_reverted',
         'account_deleted', 'admin', 'replay',
         'account_inactive', 'membership_lost'));
