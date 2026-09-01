-- Dev-only: give NOLOGIN service roles a dev login where the local
-- docker-compose stack needs one. In production such roles are
-- provisioned with credentials from a secrets manager, never in SQL.
-- Idempotent; safe to re-run.
--
-- Currently empty on purpose: every role the services connect as
-- (app_role, tenant_writer, audit_writer, audit_reader, crypto_writer)
-- is already created WITH LOGIN in infra/postgres/init.sql, and
-- `app_notification_worker` stays NOLOGIN by design until the
-- notification workers split into their own deploy unit. When that
-- split lands, add here:
--
--   ALTER ROLE app_notification_worker WITH LOGIN PASSWORD 'app_notification_worker';

SELECT 1;
