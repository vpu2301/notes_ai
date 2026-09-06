-- Reverses 0030. Dropping the grace column does not end any session: the
-- current `refresh_token_hash` is untouched, so every client holding the
-- newest token keeps working. Clients that were mid-rotation lose their
-- grace and sign in again.
DROP INDEX IF EXISTS auth_sessions_prev_refresh_idx;

ALTER TABLE auth_sessions
    DROP COLUMN IF EXISTS previous_refresh_token_hash,
    DROP COLUMN IF EXISTS rotated_at;

-- Back to 0025's set. Rows already carrying one of the two new reasons
-- would fail the narrower check, so they are put back to the closest
-- reason 0025 has a word for.
UPDATE auth_sessions
   SET revoked_reason = 'admin'
 WHERE revoked_reason IN ('account_inactive', 'membership_lost');

ALTER TABLE auth_sessions DROP CONSTRAINT auth_sessions_revoked_reason_check;

ALTER TABLE auth_sessions
    ADD CONSTRAINT auth_sessions_revoked_reason_check
    CHECK (revoked_reason IS NULL OR revoked_reason IN
        ('logout', 'user_revoked', 'revoke_others', 'mfa_change',
         'password_change', 'email_change', 'email_reverted',
         'account_deleted', 'admin', 'replay'));
