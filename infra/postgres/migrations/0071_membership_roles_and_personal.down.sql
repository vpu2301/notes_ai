-- Reverse of 0071. W1 creates no guests; the UPDATE is a safety net so the
-- old CHECK can be restored.
UPDATE tenant_memberships SET role = 'viewer' WHERE role = 'guest';
ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check
    CHECK (role IN ('owner', 'admin', 'member', 'assistant', 'viewer'));

COMMENT ON COLUMN tenant_memberships.role IS NULL;
COMMENT ON COLUMN tenants.kind IS NULL;
