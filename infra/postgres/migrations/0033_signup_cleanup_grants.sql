-- 0033 — BE-0: the deletes the stale-signup cleanup needs.
--
-- `python -m auth_service.ops.cleanup_invited` removes accounts that were
-- created by self-serve signup and never confirmed. An unconfirmed
-- account occupies its address forever — the person cannot sign up again
-- with it, and the uniform 202 means they are never told why — so it has
-- to be removable, and by a scheduled job rather than by hand.
--
-- Four narrow grants, in the spirit of 0029: each one is a decision
-- somebody made, attached to the reason, rather than a privilege that
-- arrived with a `GRANT ... ON ALL TABLES`.
--
-- ── Why DELETE on `identities` is safe to grant here ────────────────
--
-- It is the widest of the four, and the one worth arguing. Three things
-- bound it:
--
--   * `app_role` — the credential every product service connects as —
--     gains nothing. It still holds no privilege on `identities` at all,
--     and `check-identity-grants.py` fails the build if that changes.
--   * `tenant_writer` is auth-service's own pool. Nothing else in the
--     fleet can reach it, and within auth-service the only DELETE
--     statement against `identities` is in `ops/cleanup_invited.py`.
--   * The account-deletion path (IDX-A5) still does NOT delete: it
--     tombstones, rewriting the address so a login lookup can never match
--     one. That remains the way a *person* leaves. This grant is for
--     accounts that were never anybody's.
--
-- `auth_challenges` needs DELETE for the same command: an unconfirmed
-- signup usually has an open challenge, and the FK from
-- `auth_challenges.identity_id` would otherwise block the identity row.
--
-- `tenants` and `tenant_memberships` are needed to remove the empty
-- personal workspace the signup created. The command only removes one
-- when it is `kind = 'personal'` AND has at most one membership — a team
-- workspace with other people in it is never touched.

GRANT DELETE ON identities          TO tenant_writer;
GRANT DELETE ON auth_challenges     TO tenant_writer;
GRANT DELETE ON tenant_memberships  TO tenant_writer;
GRANT DELETE ON tenants             TO tenant_writer;
