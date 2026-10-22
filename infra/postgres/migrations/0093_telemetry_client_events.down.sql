ALTER TABLE telemetry_runs DROP COLUMN IF EXISTS user_wait_cross_device;
DROP INDEX IF EXISTS telemetry_client_events_once_idx;
