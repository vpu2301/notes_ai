-- Reverses 0033. The stale-signup cleanup stops working; unconfirmed
-- accounts accumulate and keep their addresses reserved. Nothing else
-- deletes from these four tables, so no other path is affected.
REVOKE DELETE ON tenants             FROM tenant_writer;
REVOKE DELETE ON tenant_memberships  FROM tenant_writer;
REVOKE DELETE ON auth_challenges     FROM tenant_writer;
REVOKE DELETE ON identities          FROM tenant_writer;
