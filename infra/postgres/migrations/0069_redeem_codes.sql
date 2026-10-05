-- 0069 — Redeem codes: a code an operator hands out puts a workspace on a
-- plan, for a time or for good, without a payment provider.
--
-- `redeem_codes` is global (a code is not any one tenant's) and holds only
-- the SHA-256 of the normalised code — a leaked table redeems nothing.
-- Neither table is readable by app_role: the one way in is
-- `redeem_code()`, SECURITY DEFINER, which checks the caller's own tenant,
-- locks the code row, and either records the redemption or raises one of
-- `redeem:unknown | redeem:expired | redeem:used_up | redeem:already`.
-- Codes are made with scripts/admin/redeem_code.py.

CREATE TABLE redeem_codes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_hash        BYTEA NOT NULL UNIQUE,
    plan             TEXT NOT NULL CHECK (plan IN ('free', 'pro', 'enterprise')),
    -- NULL = the plan stays until someone changes it.
    duration_days    INTEGER CHECK (duration_days IS NULL OR duration_days > 0),
    -- NULL = any number of workspaces.
    max_redemptions  INTEGER CHECK (max_redemptions IS NULL OR max_redemptions > 0),
    redeemed_count   INTEGER NOT NULL DEFAULT 0,
    expires_at       TIMESTAMPTZ,
    note             TEXT CHECK (char_length(note) <= 200),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE redeem_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE redeem_codes FORCE  ROW LEVEL SECURITY;

CREATE TABLE redeem_code_redemptions (
    code_id     UUID NOT NULL REFERENCES redeem_codes(id) ON DELETE CASCADE,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    redeemed_by UUID NOT NULL,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (code_id, tenant_id)
);
ALTER TABLE redeem_code_redemptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE redeem_code_redemptions FORCE  ROW LEVEL SECURITY;

-- A plan that came from a code says so (and when it ends).
ALTER TABLE workspace_billing DROP CONSTRAINT workspace_billing_provider_check;
ALTER TABLE workspace_billing ADD CONSTRAINT workspace_billing_provider_check
    CHECK (provider IN ('manual', 'stripe', 'code'));
-- A code-given plan that runs out leaves no subscription behind.
GRANT DELETE ON workspace_billing TO app_role;

CREATE FUNCTION public.redeem_code(p_tenant uuid, p_hash bytea, p_actor uuid)
    RETURNS TABLE (plan text, duration_days integer)
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
DECLARE
    c redeem_codes%ROWTYPE;
BEGIN
    IF p_tenant IS DISTINCT FROM current_setting('app.tenant_id', true)::uuid THEN
        RAISE EXCEPTION 'redeem: tenant mismatch';
    END IF;
    SELECT * INTO c FROM redeem_codes WHERE code_hash = p_hash FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'redeem:unknown';
    END IF;
    IF c.expires_at IS NOT NULL AND c.expires_at <= now() THEN
        RAISE EXCEPTION 'redeem:expired';
    END IF;
    IF EXISTS (SELECT 1 FROM redeem_code_redemptions r
               WHERE r.code_id = c.id AND r.tenant_id = p_tenant) THEN
        RAISE EXCEPTION 'redeem:already';
    END IF;
    IF c.max_redemptions IS NOT NULL AND c.redeemed_count >= c.max_redemptions THEN
        RAISE EXCEPTION 'redeem:used_up';
    END IF;
    INSERT INTO redeem_code_redemptions (code_id, tenant_id, redeemed_by)
    VALUES (c.id, p_tenant, p_actor);
    UPDATE redeem_codes SET redeemed_count = redeemed_count + 1 WHERE id = c.id;
    RETURN QUERY SELECT c.plan, c.duration_days;
END
$$;
REVOKE ALL ON FUNCTION public.redeem_code(uuid, bytea, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.redeem_code(uuid, bytea, uuid) TO app_role;
