-- Remove the dev tenants and any dev principals seeded on top of them
-- (`make seed` layers users/memberships over this migration; users
-- reference tenants with ON DELETE RESTRICT, so they go first).
DELETE FROM tenant_memberships
 WHERE tenant_id IN ('00000000-0000-0000-0000-00000000000a',
                     '00000000-0000-0000-0000-00000000000b');
DELETE FROM users
 WHERE tenant_id IN ('00000000-0000-0000-0000-00000000000a',
                     '00000000-0000-0000-0000-00000000000b');
DELETE FROM tenants
 WHERE id IN ('00000000-0000-0000-0000-00000000000a',
              '00000000-0000-0000-0000-00000000000b');
