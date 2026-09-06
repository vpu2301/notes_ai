-- Reverse of 0025. Dropping identity_totp destroys every enrolled second
-- factor; the rollback path in the runbook says so, because re-applying
-- 0025 afterwards leaves every MFA user needing to enrol again.
DROP TABLE IF EXISTS identity_recovery_codes;
DROP TABLE IF EXISTS identity_totp;

ALTER TABLE identities DROP COLUMN IF EXISTS timezone;
ALTER TABLE identities DROP COLUMN IF EXISTS locale;

ALTER TABLE auth_sessions DROP COLUMN IF EXISTS revoked_reason;
ALTER TABLE auth_sessions DROP COLUMN IF EXISTS device_name;
ALTER TABLE auth_sessions DROP COLUMN IF EXISTS last_authenticated_at;

ALTER TABLE auth_challenges DROP COLUMN IF EXISTS metadata;
-- Rows in the kinds 0025 introduced would violate the narrower constraint;
-- they are short-lived by construction, so clear them rather than fail.
DELETE FROM auth_challenges
    WHERE kind IN ('totp_enroll', 'mfa_login', 'email_change', 'reauth');
ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_kind_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_kind_check
    CHECK (kind IN ('email_login', 'mfa_totp', 'invite'));
