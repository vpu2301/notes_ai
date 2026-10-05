DROP FUNCTION IF EXISTS public.redeem_code(uuid, bytea, uuid);
REVOKE DELETE ON workspace_billing FROM app_role;
DELETE FROM workspace_billing WHERE provider = 'code';
ALTER TABLE workspace_billing DROP CONSTRAINT workspace_billing_provider_check;
ALTER TABLE workspace_billing ADD CONSTRAINT workspace_billing_provider_check
    CHECK (provider IN ('manual', 'stripe'));
DROP TABLE IF EXISTS redeem_code_redemptions;
DROP TABLE IF EXISTS redeem_codes;
