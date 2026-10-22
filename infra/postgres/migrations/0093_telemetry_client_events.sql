-- 0093 — Telemetry sprint 3: client-event ingest. Additive only.
-- One event per (run, client, event): the first report wins, a duplicate is ignored.
CREATE UNIQUE INDEX telemetry_client_events_once_idx
    ON telemetry_client_events (processing_run_id, client, event)
    WHERE processing_run_id IS NOT NULL;

-- user_wait_seconds measured across two devices (stop on one, display on another): the value
-- then rests on server-corrected clocks, not one device's clock.
ALTER TABLE telemetry_runs ADD COLUMN user_wait_cross_device BOOLEAN;
