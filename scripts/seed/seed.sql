-- Dev seed data (make seed; scripts/seed/seed.py runs this first).
-- Each user's `sub` MUST equal the Keycloak user id in
-- infra/keycloak/realm-export.json; keep the two files in lockstep.

BEGIN;

-- ── Tenants (idempotent; owned by migration 0013) ──────────────────────────
INSERT INTO tenants (id, name, display_name, locale, timezone, status) VALUES
    ('00000000-0000-0000-0000-00000000000a', 'tenant-a', 'Acme Inc',    'en', 'Europe/Kyiv', 'active'),
    ('00000000-0000-0000-0000-00000000000b', 'tenant-b', 'Globex Corp', 'en', 'Europe/Kyiv', 'active')
ON CONFLICT (id) DO NOTHING;

-- ── Users (sub = Keycloak user id from realm-export.json) ───────────────────
INSERT INTO users (sub, tenant_id, email, display_name, role, status) VALUES
    ('0a000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'admin@tenant-a.example',   'Dev Admin A',   'tenant_admin', 'active'),
    -- The only seeded account with tenant_admin and nothing else (the pure admin view).
    ('0b000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000a', 'owner@tenant-a.example',   'Dev Owner A',   'tenant_admin', 'active'),
    ('0c000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'member@tenant-a.example',  'Dev Member A',  'member',       'active'),
    ('0d000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'viewer@tenant-a.example',  'Dev Viewer A',  'viewer',       'active'),
    ('0e000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'auditor@tenant-a.example', 'Dev Auditor A', 'auditor',      'active'),
    ('0c000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000b', 'member@tenant-b.example',  'Dev Member B',  'member',       'active'),
    ('0a000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000b', 'admin@tenant-b.example',   'Dev Admin B',   'tenant_admin', 'active')
-- Conflict on (tenant_id, email), NOT on sub: Keycloak's admin REST API mints
-- its own user id (KC 24), so a hand-created account carries a different sub
-- for the same email and conflicting on sub would abort the seed.
ON CONFLICT (tenant_id, email) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        role         = EXCLUDED.role,
        status       = EXCLUDED.status;

-- ── Tenant branding (idempotent, dev-cosmetic) ──────────────────────────────
UPDATE tenants SET
    legal_name      = 'Acme Inc',
    slug            = 'tenant-a',
    contact_email   = 'contact@tenant-a.example',
    phone_number    = '+380 44 000 0001',
    website         = 'https://tenant-a.example',
    address_line1   = '1 Khreshchatyk St',
    city            = 'Kyiv',
    country         = 'Ukraine',
    is_active       = true
WHERE id = '00000000-0000-0000-0000-00000000000a';

UPDATE tenants SET
    legal_name      = 'Globex Corporation LLC',
    slug            = 'tenant-b',
    contact_email   = 'contact@tenant-b.example',
    phone_number    = '+380 44 000 0002',
    website         = 'https://tenant-b.example',
    address_line1   = '2 Deribasivska St',
    city            = 'Odesa',
    country         = 'Ukraine',
    is_active       = true
WHERE id = '00000000-0000-0000-0000-00000000000b';

-- ── Tenant memberships (platform role → management role) ───────────────────
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
SELECT
    u.tenant_id,
    u.sub,
    CASE u.role
        WHEN 'tenant_admin' THEN 'owner'
        WHEN 'member'       THEN 'member'
        WHEN 'auditor'      THEN 'viewer'
        ELSE 'viewer'
    END,
    'active'
FROM users u
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- Dev Admin A also administers tenant-B (multi-tenant data for the switcher).
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
VALUES ('00000000-0000-0000-0000-00000000000b', '0a000000-0000-0000-0000-00000000000a', 'admin', 'active')
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Example workspace "Sunrise Studio", owned by Dev Admin A ───────────────
INSERT INTO tenants (
    id, name, display_name, legal_name, slug, locale, timezone, status, is_active,
    contact_email, phone_number, website,
    address_line1, city, country
) VALUES (
    '0000c111-0000-0000-0000-000000000001',
    'sunrise', 'Sunrise Studio', 'Sunrise Studio LLC', 'sunrise', 'en', 'Europe/Kyiv', 'active', true,
    'hello@sunrise.example', '+380 44 111 1111', 'https://sunrise.example',
    '5 Sichovykh Striltsiv St', 'Kyiv', 'Ukraine'
)
ON CONFLICT (id) DO UPDATE SET
    display_name  = EXCLUDED.display_name,
    legal_name    = EXCLUDED.legal_name,
    slug          = EXCLUDED.slug,
    contact_email = EXCLUDED.contact_email,
    phone_number  = EXCLUDED.phone_number,
    website       = EXCLUDED.website,
    address_line1 = EXCLUDED.address_line1,
    city          = EXCLUDED.city,
    country       = EXCLUDED.country,
    is_active     = EXCLUDED.is_active;

-- Dev Admin A owns the example workspace.
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
VALUES ('0000c111-0000-0000-0000-000000000001', '0a000000-0000-0000-0000-00000000000a', 'owner', 'active')
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Notes AI's own account (the vendor): backs the #/company console ───────
-- tenant_admin + auditor in Keycloak; anchored in tenant-a. Reconciled on email.
INSERT INTO users (sub, tenant_id, email, display_name, role, status)
VALUES (
    '0f000000-0000-0000-0000-00000000000f',   -- used only on a fresh realm import
    '00000000-0000-0000-0000-00000000000a',
    'vpu2301@gmail.com', 'Notes AI Owner', 'tenant_admin', 'active'
)
ON CONFLICT (tenant_id, email) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        role         = EXCLUDED.role,
        status       = EXCLUDED.status;

-- ── Notes AI owner: member of tenant-a only ───────────────────────────────
-- Never a cross join over every tenant (integration runs leave throwaway
-- workspaces behind). Keyed off the email.
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
SELECT t.id, u.sub, 'owner', 'active'
FROM tenants t
CROSS JOIN users u
WHERE u.email = 'vpu2301@gmail.com'
  AND t.name = 'tenant-a'   -- where the owner's notes live
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Identities for every seeded user ──────────────────────────────────────
-- Authorship FKs point at identities (0028); the 0027 backfill ran on an empty
-- DB, so without this every POST /v1/notes 500s. legacy_idp = true: these
-- accounts authenticate through Keycloak.
INSERT INTO identities (id, email, email_verified_at, display_name,
                        status, locale, timezone, legacy_idp)
SELECT u.sub, lower(u.email), u.created_at, u.display_name,
       'active', 'en', 'UTC', true
FROM users u
WHERE NOT EXISTS (SELECT 1 FROM identities i WHERE i.id = u.sub)
  AND NOT EXISTS (SELECT 1 FROM identities x WHERE x.email = lower(u.email))
ON CONFLICT (id) DO NOTHING;

UPDATE identities i
SET last_tenant_id = u.tenant_id
FROM users u
WHERE u.sub = i.id AND i.last_tenant_id IS NULL;

-- Fill a missing name from the users row on re-seed. Never overwrite one that
-- is set: a person who renamed themselves (PATCH /auth/me writes identities
-- only) must keep that name across `make seed`, legacy_idp or not.
UPDATE identities i
SET display_name = u.display_name
FROM users u
WHERE u.sub = i.id
  AND i.legacy_idp
  AND (i.display_name IS NULL OR btrim(i.display_name) = '');

COMMIT;
