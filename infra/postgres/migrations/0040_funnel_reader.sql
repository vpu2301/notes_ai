-- 0040 — Sprint 22: a read-only role for the loop funnel.
--
-- Grafana's Postgres datasource and the weekly report read the funnel
-- across every tenant. That read joins `referrals.ref_code` to
-- `note_share_links.ref_code` — the one join the product itself never
-- makes (0036) — so it gets its own role with SELECT and nothing else,
-- and a permissive SELECT policy on each FORCE-RLS table it touches.
-- The role is created here (idempotently) as well as in init.sql so an
-- existing database gets it on migrate-up.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'funnel_reader') THEN
        CREATE ROLE funnel_reader LOGIN PASSWORD 'funnel_reader';
    END IF;
END $$;

GRANT SELECT ON tenants, notes, note_share_links, share_link_responses, referrals TO funnel_reader;

CREATE POLICY funnel_reader_select ON tenants FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON notes FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON note_share_links FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON share_link_responses FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON referrals FOR SELECT TO funnel_reader USING (true);
