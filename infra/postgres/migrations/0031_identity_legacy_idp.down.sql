-- Reverses 0031. Dropping `legacy_idp` loses the record of who
-- authenticates through Keycloak, which BE-3 needs to refuse a
-- single-factor email code to a Keycloak-MFA user. Do not roll this back
-- while MDX_IDP_MODE is `dual` — set the mode to `keycloak` first, which
-- takes the email-code endpoints down and makes the flag unread.
--
-- `mfa_enabled` is deliberately NOT reset: it now holds the truth (0031
-- was the first thing ever to write it), and zeroing it would leave the
-- column claiming nobody has a second factor.
DROP INDEX IF EXISTS identities_legacy_idp_idx;

ALTER TABLE identities DROP COLUMN IF EXISTS legacy_idp;
