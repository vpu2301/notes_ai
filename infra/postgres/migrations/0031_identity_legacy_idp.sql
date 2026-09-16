-- BE-1 (batch `first-account`) — mark which identities still authenticate
-- through Keycloak, and write down the bridge rule that keeps content
-- authorship working until IDX-B2.
--
-- ── Why a flag and not an inference ──────────────────────────────────
--
-- During the `dual` period (ADR-0047) auth-service has to answer one
-- question on every email-code login: "is this person's real credential
-- somewhere I cannot see?" For an identity backfilled from `users` by
-- migration 0027, the answer is yes — their password lives in Keycloak,
-- and so does their second factor.
--
-- It could *almost* be inferred from `password_hash IS NULL`, and that is
-- exactly why it must not be. A brand-new identity created by BE-3 also
-- has no password hash (they signed up with a code and have not set one),
-- so the inference conflates "authenticates elsewhere" with "has not
-- chosen a password yet" — two populations with opposite handling in
-- BE-3's `use_password` rule. IDX-A4 will also start writing
-- `password_hash` for migrated users, which would silently flip the
-- inference for people who have not migrated at all.
--
-- So it is recorded, once, at the moment it is true.
--
-- ── The bridge rule (ADR-IDX-03: `users` is a bridge until B2) ───────
--
-- The batch brief states that `note_versions.created_by`,
-- `notes.primary_author_id` and `autocomplete_phrases/snippets.owner_user_id`
-- still reference `users(sub)`. **They do not** — migration 0028 already
-- swapped every one of them to `identities(id)`, so an identity without a
-- `users` row can author content perfectly well. The brief was written
-- against the pre-0028 schema.
--
-- The bridge row is still required, for a different reason, and the
-- reason is worth writing down because it is the one a future reader
-- will otherwise have to rediscover: `users` is how the rest of the
-- estate turns a `sub` into a person. note-service reads it to offer
-- share recipients; notification-service reads it to find an address to
-- mail. An identity without one holds a perfectly valid token, writes
-- notes nobody can share with them, and receives no mail — a failure
-- that is silent on every path that produces it.
--
-- So every NEW identity (BE-3) still gets one, in the SAME transaction as
-- its personal tenant:
--
--     INSERT INTO users (sub, tenant_id, email, display_name, role, status)
--     VALUES (identity.id, <personal tenant id>, identity.email,
--             identity.display_name, 'member', 'active');
--
-- `scripts/ci/check-identity-bridge.py` asserts the invariant;
-- `create_with_personal_workspace` and `ensure_personal_workspace` are
-- the only sanctioned writers. The check retires when IDX-B2 finishes
-- moving the sub→person lookups off `users` altogether.

ALTER TABLE identities
    -- true  → authenticates through Keycloak (password + any MFA live
    --         there); BE-3 refuses a single-factor email-code session
    --         when this is true AND mfa_enabled is true.
    -- false → native: this service owns every credential it has.
    ADD COLUMN legacy_idp BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN identities.legacy_idp IS
    'Credentials live in Keycloak, not here. Set by the 0027 backfill; '
    'cleared by IDX-A4 when the person sets a native password. '
    'See ADR-0047 (dual-issuer period).';

-- Every identity that exists right now got here through 0027's backfill:
-- there is no native signup path in any deployed mode yet (email_code is
-- mounted only when MDX_IDP_MODE is dual or native, and no deployment has
-- been either). The condition is written against `users` anyway rather
-- than "all rows", so re-running against a database where someone HAS
-- signed up natively does not mislabel them.
UPDATE identities i
   SET legacy_idp = true
  FROM users u
 WHERE u.sub = i.id;

CREATE INDEX identities_legacy_idp_idx ON identities (legacy_idp)
    WHERE legacy_idp;

-- `identities.mfa_enabled` exists (0024) but nothing has ever written it:
-- 0027's backfill INSERT does not list the column, so every backfilled
-- identity carries the DEFAULT false — including people who have a
-- Keycloak authenticator app enrolled right now. IDX-A1 §H specified this
-- mapping; it was missed. Left as it is, BE-3 would hand a Keycloak-MFA
-- user a single-factor native session, which is a downgrade of their
-- account security performed silently on their behalf.
--
-- BE-3 reads the PAIR: `legacy_idp AND mfa_enabled` is what makes an
-- email code an unacceptable single factor.
UPDATE identities i
   SET mfa_enabled = (u.mfa_enrolled_at IS NOT NULL)
  FROM users u
 WHERE u.sub = i.id
   AND i.mfa_enabled IS DISTINCT FROM (u.mfa_enrolled_at IS NOT NULL);
