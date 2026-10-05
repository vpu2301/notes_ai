-- 0068 — Billing: a workspace's plan can change, and the payment
-- provider has somewhere to put its references.
--
-- `tenants.plan` / `plan_limits` (0038) are the facts the product reads;
-- they stay where they are. What is new:
--
-- * `set_tenant_plan` — the one way the API changes a plan. SECURITY
--   DEFINER because app_role cannot write `tenants`, and it refuses any
--   tenant but the connection's own (the 0041 pattern).
-- * `workspace_billing` — the provider's side: which customer and which
--   subscription this workspace is, and their state. Empty until a
--   provider is connected; Stripe's webhook is what will fill it. Never a
--   card number, never an address — those stay with the provider.

CREATE FUNCTION public.set_tenant_plan(p_tenant uuid, p_plan text, p_limits jsonb)
    RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
BEGIN
    IF p_tenant IS DISTINCT FROM current_setting('app.tenant_id', true)::uuid THEN
        RAISE EXCEPTION 'plan: tenant mismatch';
    END IF;
    UPDATE public.tenants
       SET plan = p_plan, plan_limits = p_limits, updated_at = now()
     WHERE id = p_tenant;
END
$$;
REVOKE ALL ON FUNCTION public.set_tenant_plan(uuid, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_tenant_plan(uuid, text, jsonb) TO app_role;

CREATE TABLE workspace_billing (
    tenant_id            UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    provider             TEXT NOT NULL CHECK (provider IN ('manual', 'stripe')),
    -- The provider's own ids (Stripe: cus_…, sub_…).
    customer_ref         TEXT CHECK (char_length(customer_ref) <= 255),
    subscription_ref     TEXT CHECK (char_length(subscription_ref) <= 255),
    status               TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'trialing', 'past_due', 'canceled')),
    current_period_end   TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT false,
    updated_by           UUID,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE workspace_billing ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_billing FORCE  ROW LEVEL SECURITY;
CREATE POLICY workspace_billing_tenant_all ON workspace_billing
    FOR ALL TO app_role
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON workspace_billing TO app_role;
