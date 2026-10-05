-- 0039 — Sprint 22: the product sends the recipient link, and remembers.
--
-- Until now every client handed a recipient link to the sender's own
-- mail program, so nobody could tell whether it was delivered. The mail
-- is now sent by note-service itself — inline, through the same SMTP
-- adapter `/share/email` has used since sprint 16, so there is no
-- outbox, no worker and no secret at rest: the share URL exists in the
-- request and in the recipient's inbox, nowhere in between.
--
-- Two additions:
--   * per-link delivery state on `note_share_links` (the sender's
--     "Sent → Opened → Responded" chips);
--   * `share_mail_suppressions` — one-click opt-out. GLOBAL by design:
--     an opt-out is a fact about a person, not about a workspace, so it
--     is keyed by a peppered hash of the address and reachable from a
--     tenant-scoped connection only through the two SECURITY DEFINER
--     helpers below (the 0016 resolver pattern). No address is stored.

CREATE TYPE share_delivery_status AS ENUM ('not_sent', 'sent', 'failed', 'suppressed');

ALTER TABLE note_share_links
    ADD COLUMN delivery_status share_delivery_status NOT NULL DEFAULT 'not_sent',
    ADD COLUMN sent_at         TIMESTAMPTZ,
    ADD COLUMN send_count      INTEGER NOT NULL DEFAULT 0,
    -- The error CLASS of the last failed send, never the message.
    ADD COLUMN last_send_error TEXT NOT NULL DEFAULT '';

CREATE TABLE share_mail_suppressions (
    email_hash  BYTEA PRIMARY KEY,   -- sha256(pepper || lower(email))
    reason      TEXT NOT NULL CHECK (reason IN ('unsubscribed', 'hard_bounce', 'abuse_report')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE share_mail_suppressions ENABLE ROW LEVEL SECURITY;
ALTER TABLE share_mail_suppressions FORCE  ROW LEVEL SECURITY;
-- Operators erase through tenant_writer (docs/runbooks/notes.md); the
-- services never touch the table directly.
CREATE POLICY share_mail_suppressions_writer_all ON share_mail_suppressions
    FOR ALL TO tenant_writer
    USING (true)
    WITH CHECK (true);
GRANT SELECT, INSERT, DELETE ON share_mail_suppressions TO tenant_writer;

CREATE FUNCTION public.is_share_mail_suppressed(p_hash bytea)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT EXISTS (SELECT 1 FROM public.share_mail_suppressions WHERE email_hash = p_hash)
$$;

CREATE FUNCTION public.add_share_mail_suppression(p_hash bytea, p_reason text)
    RETURNS void
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = public
AS $$
    INSERT INTO public.share_mail_suppressions (email_hash, reason)
    VALUES (p_hash, p_reason)
    ON CONFLICT (email_hash) DO NOTHING
$$;

-- The unsubscribe link carries a link id, not a token: this is how the
-- anonymous route learns which tenant to open before it may read the row.
CREATE FUNCTION public.tenant_of_share_link(p_link_id uuid)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
AS $$
    SELECT tenant_id FROM public.note_share_links WHERE id = p_link_id
$$;

REVOKE ALL ON FUNCTION public.is_share_mail_suppressed(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.add_share_mail_suppression(bytea, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tenant_of_share_link(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_share_mail_suppressed(bytea) TO app_role;
GRANT EXECUTE ON FUNCTION public.add_share_mail_suppression(bytea, text) TO app_role;
GRANT EXECUTE ON FUNCTION public.tenant_of_share_link(uuid) TO app_role;
