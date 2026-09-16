-- Reverse of 0032. The kind list goes back to 0025's set, so any
-- outstanding signup challenges must go first — they would violate the
-- narrower CHECK. They are inert rows (a code nobody can redeem once the
-- endpoint is gone), so deleting them loses nothing.
DELETE FROM auth_challenges WHERE kind = 'signup_verify';

ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_kind_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_kind_check
    CHECK (kind IN ('email_login', 'mfa_totp', 'invite',
                    'totp_enroll', 'mfa_login', 'email_change', 'reauth'));

COMMENT ON COLUMN identities.password_hash IS NULL;
COMMENT ON COLUMN identities.email_verified_at IS NULL;
