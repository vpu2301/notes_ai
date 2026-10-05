-- 0036 — Sprint 19: referral leads from the shared page's CTA (auth-service).
--
-- A recipient of a shared note clicks "Create your own workspace free",
-- lands on /join?ref=<ref_code> and leaves an e-mail address. This sprint
-- that is a fake door — nothing is created, the row is the lead — and
-- Sprint 21 fills `referred_sub` / `referred_tenant_id` when the click
-- becomes a real workspace.
--
-- Global by design: `ref_code` comes from the sharer's tenant and the
-- lead belongs to nobody's tenant yet, so there is no tenant_id and no
-- tenant policy. `ref_code` is NOT a foreign key — it crosses the tenant
-- boundary on purpose and carries no tenant information (0035). Only
-- `tenant_writer` (auth-service) may touch the table; `app_role` has no
-- access at all. RLS is still switched on with FORCE and a single
-- writer-only policy — the shape 0024 gave `auth_challenges` — so the
-- `check-rls` gate holds and any future grant to another role starts
-- from "sees nothing" rather than "sees everything".

CREATE TABLE referrals (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_code           TEXT NOT NULL CHECK (char_length(ref_code) <= 32),
    -- Fake-door capture. NULL once Sprint 21 records a real signup.
    lead_email         TEXT CHECK (lead_email IS NULL OR char_length(lead_email) <= 320),
    lead_consent_at    TIMESTAMPTZ,
    referred_sub       UUID,
    referred_tenant_id UUID,
    source             TEXT NOT NULL DEFAULT 'share_cta',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX referrals_ref_code_idx ON referrals (ref_code);
-- The same address through the same link is one lead, not a counter.
CREATE UNIQUE INDEX referrals_lead_email_ref_idx
    ON referrals (lower(lead_email), ref_code)
    WHERE lead_email IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON referrals TO tenant_writer;

ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;
ALTER TABLE referrals FORCE  ROW LEVEL SECURITY;

CREATE POLICY referrals_writer_all ON referrals
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);
