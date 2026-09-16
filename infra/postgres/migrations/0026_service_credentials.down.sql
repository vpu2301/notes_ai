-- Reverse of 0026. Dropping the secrets table destroys every device's
-- credential: re-applying leaves each room needing a re-provision, so the
-- runbook's rollback section says to revoke rather than roll back.
DROP TABLE IF EXISTS service_credential_secrets;
DROP TABLE IF EXISTS service_credentials;
