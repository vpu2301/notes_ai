DROP FUNCTION IF EXISTS notification_active_tenant_ids();
DROP FUNCTION IF EXISTS notification_tenants_with_due_outbox();
DROP TABLE IF EXISTS audit.notification_dead_letters;
DROP TABLE IF EXISTS notification_digest_progress;
DROP TABLE IF EXISTS notification_outbox;
DROP TABLE IF EXISTS notification_user_settings;
DROP TABLE IF EXISTS notification_preferences;
DROP TABLE IF EXISTS notifications;
-- The app_notification_worker role is left in place: roles are
-- cluster-global and other objects may still reference it; init.sql /
-- this migration recreate it idempotently.
