DROP FUNCTION IF EXISTS public.tenant_of_share_link(uuid);
DROP FUNCTION IF EXISTS public.add_share_mail_suppression(bytea, text);
DROP FUNCTION IF EXISTS public.is_share_mail_suppressed(bytea);
DROP TABLE IF EXISTS share_mail_suppressions;
ALTER TABLE note_share_links
    DROP COLUMN IF EXISTS last_send_error,
    DROP COLUMN IF EXISTS send_count,
    DROP COLUMN IF EXISTS sent_at,
    DROP COLUMN IF EXISTS delivery_status;
DROP TYPE IF EXISTS share_delivery_status;
