DROP TABLE IF EXISTS share_abuse_reports;
DROP TABLE IF EXISTS share_link_otps;
DROP FUNCTION IF EXISTS public.set_tenant_sharing_policy(uuid, jsonb);
ALTER TABLE note_share_links
    DROP COLUMN IF EXISTS last_seen_version_id,
    DROP COLUMN IF EXISTS verified_at;
ALTER TABLE tenants DROP COLUMN IF EXISTS sharing_policy;
