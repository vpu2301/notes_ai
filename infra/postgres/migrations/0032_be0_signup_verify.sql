-- BE-0 (batch `first-account`) — self-serve signup with a password.
--
-- One new challenge kind and nothing else. Everything signup needs is
-- already in 0024: `identities.password_hash` (nullable, written for the
-- first time here), `identities.email_verified_at` (nullable — an account
-- exists before its address is proved), and `auth_challenges`, whose
-- `email` column is deliberately NOT an FK precisely so a code can be
-- outstanding for an address (0024's own comment says so).
--
-- ── Why a separate kind from `email_login` ──────────────────────────
--
-- They look alike — six digits, ten minutes, five attempts — and they buy
-- completely different things. An `email_login` code is a *credential*:
-- spending it opens a session. A `signup_verify` code proves an address
-- is reachable and buys nothing on its own; the session that follows comes
-- from the password the person then supplies.
--
-- Sharing one kind would mean a code mailed for one purpose could be
-- redeemed for the other. Concretely: a `signup_verify` code intercepted
-- from a mailbox would become a working sign-in at `/auth/email/verify`,
-- turning a "confirm your address" mail into a bearer credential. The
-- CHECK below is what makes `latest_open_for_email(kind=...)` a real
-- boundary rather than a convention.

ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_kind_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_kind_check
    CHECK (kind IN ('email_login', 'mfa_totp', 'invite',
                    'totp_enroll', 'mfa_login', 'email_change', 'reauth',
                    'signup_verify'));

-- Signup writes a verifier for the first time. The column has existed
-- since 0024; this comment is where a reader finds out who fills it.
COMMENT ON COLUMN identities.password_hash IS
    'scrypt verifier (libs/crypto.passwords format), or NULL for an identity '
    'that has never chosen a password — a code-only signup (BE-3) or an '
    'identity whose credential still lives in Keycloak (see legacy_idp).';

COMMENT ON COLUMN identities.email_verified_at IS
    'When the address was proved reachable. NULL means signup created the '
    'account but the mailed code has not been entered yet: the account may '
    'not start a session, and /auth/login answers 403 email_not_verified.';
