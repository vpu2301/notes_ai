ALTER TABLE tenants
    DROP COLUMN IF EXISTS plan_limits,
    DROP COLUMN IF EXISTS signup_source,
    DROP COLUMN IF EXISTS plan;
