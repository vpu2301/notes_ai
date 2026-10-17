UPDATE tenants SET status = 'active', is_active = true WHERE status = 'archived';
ALTER TABLE tenants DROP CONSTRAINT tenants_status_check;
ALTER TABLE tenants ADD CONSTRAINT tenants_status_check
    CHECK (status IN ('active', 'suspended', 'dissolved'));
