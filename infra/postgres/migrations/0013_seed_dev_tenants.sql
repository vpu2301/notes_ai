-- 0013 — seed the two dev tenants referenced by the Keycloak
-- realm-export.json. Idempotent on re-apply (ON CONFLICT DO NOTHING).
--
-- Production environments do *not* apply this migration: tenants are
-- created by the auth-service onboarding flow. Gating this behind a
-- checked-in migration keeps the dev experience one-command
-- (`make migrate-up`) without leaking dev data into prod.
--
-- The UUIDs are pinned because infra/keycloak/realm-export.json carries
-- them as the `tid` user attribute; `make seed` (scripts/seed/seed.py)
-- layers users, memberships, and branding on top.

INSERT INTO tenants (id, name, display_name, locale, timezone, status)
VALUES
    ('00000000-0000-0000-0000-00000000000a', 'tenant-a', 'Acme Inc',    'en', 'Europe/Kyiv', 'active'),
    ('00000000-0000-0000-0000-00000000000b', 'tenant-b', 'Globex Corp', 'en', 'Europe/Kyiv', 'active')
ON CONFLICT (id) DO NOTHING;
