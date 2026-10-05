-- 0070 — A paid plan is billed monthly or yearly. The interval is part of
-- what the workspace bought (Stripe: which price), so it lives next to
-- the provider's references. Existing rows were all monthly.
ALTER TABLE workspace_billing
    ADD COLUMN billing_interval TEXT NOT NULL DEFAULT 'monthly'
        CHECK (billing_interval IN ('monthly', 'yearly'));
