-- 0020 — Calendar links (iCal / ICS feeds) next to the Google connection.
--
-- A deployment without a Google OAuth client can still feed the home
-- page's "Coming up" list: every calendar product hands out a private
-- subscription address (Google Calendar → Settings → "Secret address in
-- iCal format"; Outlook → "Publish calendar"; iCloud → "Public calendar").
-- note-service fetches that URL on demand and parses the ICS itself —
-- no OAuth, no client id, no third party in the middle.
--
-- Such a link is a new `provider` ('ics') on the same table, so the
-- clients, the picker and the audit trail need no second code path:
--
--   * `token_blob`     holds the enveloped {"feed_url": …} — the secret
--                      address IS the credential; anyone holding it reads
--                      the calendar, so it is sealed like a token.
--   * `account_email`  holds the feed's display label (the calendar's
--                      X-WR-CALNAME, or the host) — a link has no account.
--   * `feed_fingerprint` is sha256(url) so adding the same link twice
--                      updates the row instead of duplicating it, without
--                      the plaintext URL ever being indexed.

ALTER TABLE calendar_connections
    DROP CONSTRAINT calendar_connections_provider_check;
ALTER TABLE calendar_connections
    ADD CONSTRAINT calendar_connections_provider_check
    CHECK (provider IN ('google', 'ics'));

ALTER TABLE calendar_connections
    ADD COLUMN feed_fingerprint TEXT;

-- One LIVE row per link; a revoked one stays as history.
CREATE UNIQUE INDEX calendar_connections_feed_idx
    ON calendar_connections (tenant_id, user_sub, feed_fingerprint)
    WHERE revoked_at IS NULL AND feed_fingerprint IS NOT NULL;
