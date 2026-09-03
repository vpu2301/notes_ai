DROP INDEX IF EXISTS calendar_connections_feed_idx;
-- Rows of the dropped provider would violate the narrower check.
UPDATE calendar_connections SET revoked_at = now() WHERE provider = 'ics' AND revoked_at IS NULL;
DELETE FROM calendar_connections WHERE provider = 'ics';
ALTER TABLE calendar_connections DROP COLUMN IF EXISTS feed_fingerprint;
ALTER TABLE calendar_connections
    DROP CONSTRAINT calendar_connections_provider_check;
ALTER TABLE calendar_connections
    ADD CONSTRAINT calendar_connections_provider_check
    CHECK (provider IN ('google'));
