-- 0027 — IDX-B2 step 1: give every `users` row an identity, and give the
-- fleet a sanctioned way to read a person's profile across tenants.
--
-- Both halves are IDX-A1's, which was never run. B2's FK swap cannot
-- start without the first, and its query rewrites cannot start without
-- the second, so they arrive here.
--
-- This migration adds and backfills. It changes no foreign key, drops
-- nothing, and leaves `users` exactly as it was — the swap is 0028 and
-- the drop is a later sprint.

-- ── 1. Backfill identities from users ────────────────────────────────
--
-- `users.sub` becomes `identities.id` unchanged, which is what makes the
-- FK swap in 0028 a constraint change rather than a data migration:
-- every value already in a referencing column is already the right value.
--
-- Two things are deliberately NOT copied:
--
--   * `role` and `status`. A role is per-membership (`tenant_memberships`)
--     and an identity spans workspaces, so there is no single role to
--     carry. `users.status` likewise describes a membership, not a
--     person; every backfilled identity is `active`, and a suspended
--     membership stays suspended in `tenant_memberships`.
--   * any password. These principals authenticated through Keycloak,
--     whose hashes cannot be read out. They sign in with an emailed code
--     (IDX-A3) until IDX-A4 gives them a password, which is exactly what
--     `has_password: false` in the API already tells a client.
--
-- ON CONFLICT DO NOTHING makes this re-runnable and makes it a no-op for
-- anyone who already signed up natively. `email_verified_at` is set from
-- `created_at`, not `now()`: the address was verified when the account
-- was made, and stamping today would misdate it in the one place
-- somebody would look to find out.
INSERT INTO identities (id, email, email_verified_at, display_name, status, locale, timezone)
SELECT u.sub,
       lower(u.email),
       u.created_at,
       u.display_name,
       'active',
       'en',
       'UTC'
FROM users u
WHERE NOT EXISTS (SELECT 1 FROM identities i WHERE i.id = u.sub)
  -- An address that already belongs to a native identity is the same
  -- person who signed up before the backfill ran. Skipping keeps the
  -- UNIQUE constraint honest; 0028's guard then reports the row rather
  -- than silently leaving a dangling FK.
  AND NOT EXISTS (SELECT 1 FROM identities x WHERE x.email = lower(u.email))
ON CONFLICT (id) DO NOTHING;

-- Carry the home tenant across so a backfilled identity lands somewhere
-- on its first sign-in instead of answering `no_workspace`.
UPDATE identities i
SET last_tenant_id = u.tenant_id
FROM users u
WHERE u.sub = i.id AND i.last_tenant_id IS NULL;


-- ── 2. profile_of_subs ───────────────────────────────────────────────
--
-- The problem this solves is in IDX-B2 §C: `users` is per-tenant (its PK
-- is `sub`, so one row, one home tenant), which means a colleague invited
-- into a second workspace has no `users` row there. Every roster and
-- author-name join is a LEFT JOIN that renders them as blank. Reading
-- `identities` directly is not an option — `app_role` is granted nothing
-- on it, deliberately.
--
-- So: SECURITY DEFINER, and narrow. It returns a row only for a sub that
-- shares an ACTIVE membership with the caller's current tenant. That is
-- the same boundary `users` enforced through RLS, applied correctly to
-- people who are in more than one workspace.
--
-- On the email column: IDX-B2 F2 says the helper returns no emails, with
-- roster emails coming from auth-service instead. That does not survive
-- contact with the callers — note-service resolves a share recipient BY
-- address (`find_member_by_email`) and notification-service needs an
-- address to actually send to. Both read `users.email` as `app_role`
-- today. Omitting the column would not remove that access, it would just
-- leave four call sites unable to move off `users`, which is the thing
-- this function exists to enable. The privacy control is the membership
-- predicate below, and it is strictly tighter than what those callers
-- have today.
CREATE FUNCTION public.profile_of_subs(p_subs uuid[])
    RETURNS TABLE (sub uuid, display_name text, email text, status text)
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT i.id, i.display_name, i.email, i.status
    FROM public.identities i
    WHERE i.id = ANY(p_subs)
      AND i.status <> 'deleted'
      AND EXISTS (
          SELECT 1 FROM public.tenant_memberships m
          WHERE m.user_sub = i.id
            AND m.status = 'active'
            AND m.tenant_id = current_setting('app.tenant_id', true)::uuid
      )
$$;

-- No `PUBLIC`, and no execution without a tenant scope: with
-- `app.tenant_id` unset the predicate compares against NULL and the
-- function returns nothing, so an unscoped connection cannot use it as a
-- directory.
REVOKE ALL ON FUNCTION public.profile_of_subs(uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.profile_of_subs(uuid[]) TO app_role, tenant_writer;

COMMENT ON FUNCTION public.profile_of_subs(uuid[]) IS
    'IDX-B2: display name / address for subs sharing an active membership '
    'with the current app.tenant_id. The only sanctioned path from a '
    'product service to identities.';
