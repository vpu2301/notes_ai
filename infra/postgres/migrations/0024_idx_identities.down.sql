-- Reverse of 0024. The platform tenant is removed last and only if nothing
-- was filed against it; a DELETE that fails on an FK is the right outcome
-- (an audit trail that references it must not be orphaned by a rollback).
DROP TABLE IF EXISTS auth_sessions;
DROP TABLE IF EXISTS auth_challenges;
DROP TABLE IF EXISTS identities;

DROP INDEX IF EXISTS tenants_kind_idx;
ALTER TABLE tenants DROP COLUMN IF EXISTS kind;

DELETE FROM tenants WHERE id = '00000000-0000-0000-0000-0000000000f1';
