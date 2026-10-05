-- 0038 — Sprint 21: the free plan is a fact about a tenant, recorded now.
--
-- Self-serve signup (BE-0, `onboarding_service`) creates a personal
-- workspace. From this sprint that workspace is on the `free` plan and
-- knows how it came to exist: `self_serve` from /signup, `referral` when
-- the person arrived through a shared note's CTA (Sprint 19 `ref_code`).
-- Limits are RECORDED, not enforced — enforcement is a pricing decision
-- and can arrive without a data migration because the numbers are here.
--
-- Everything that existed before is `legacy` / `admin`, except the
-- personal workspaces BE-0 already created, which are exactly what
-- `free` / `self_serve` means.

ALTER TABLE tenants
    ADD COLUMN plan          TEXT NOT NULL DEFAULT 'legacy'
                             CHECK (plan IN ('legacy', 'free', 'pro', 'enterprise')),
    ADD COLUMN signup_source TEXT NOT NULL DEFAULT 'admin'
                             CHECK (signup_source IN ('admin', 'self_serve', 'referral')),
    ADD COLUMN plan_limits   JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE tenants
SET plan = 'free',
    signup_source = 'self_serve',
    plan_limits = '{"notes_per_month": 50, "members": 3}'::jsonb
WHERE kind = 'personal';
