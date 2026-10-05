DROP POLICY IF EXISTS funnel_reader_select ON referrals;
DROP POLICY IF EXISTS funnel_reader_select ON share_link_responses;
DROP POLICY IF EXISTS funnel_reader_select ON note_share_links;
DROP POLICY IF EXISTS funnel_reader_select ON notes;
DROP POLICY IF EXISTS funnel_reader_select ON tenants;
REVOKE SELECT ON tenants, notes, note_share_links, share_link_responses, referrals FROM funnel_reader;
-- The role itself stays: dropping a role a datasource is configured with
-- is an operator's decision, not a rollback's.
