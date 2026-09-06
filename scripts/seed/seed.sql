-- Dev seed data — aligns the DB with the Keycloak realm-export.
-- Run via: make seed  (scripts/seed/seed.py executes this file first,
-- then layers templates, voice commands, and the autocomplete starter
-- corpus on top).
--
-- Authoritative schema lives in infra/postgres/migrations/0001.
--   tenants(id, name, display_name, locale, timezone, status, …)
--   users(sub PK, tenant_id, email, display_name, role, status, …)
-- Roles are the five platform roles: tenant_admin, member, viewer,
-- auditor, service.
--
-- Tenants `tenant-a` (…00a) and `tenant-b` (…00b) are created by
-- migration 0013_seed_dev_tenants; we only (idempotently) ensure they
-- exist here so this script is self-contained, then seed the users.
--
-- IMPORTANT: each user's `sub` MUST equal the Keycloak user id pinned in
-- infra/keycloak/realm-export.json — that 1:1 mapping is what lets token
-- `sub` claims join to DB rows (and lets auth-service resolve a tenant
-- from a sub). Keep the two files in lockstep.

BEGIN;

-- ── Tenants (idempotent; owned by migration 0013) ──────────────────────────
INSERT INTO tenants (id, name, display_name, locale, timezone, status) VALUES
    ('00000000-0000-0000-0000-00000000000a', 'tenant-a', 'Acme Inc',    'en', 'Europe/Kyiv', 'active'),
    ('00000000-0000-0000-0000-00000000000b', 'tenant-b', 'Globex Corp', 'en', 'Europe/Kyiv', 'active')
ON CONFLICT (id) DO NOTHING;

-- ── Users (sub = Keycloak user id from realm-export.json) ───────────────────
INSERT INTO users (sub, tenant_id, email, display_name, role, status) VALUES
    ('0a000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'admin@tenant-a.example',   'Dev Admin A',   'tenant_admin', 'active'),
    -- The ONLY seeded account with tenant_admin and NOTHING else. Dev
    -- Admin A above deliberately also holds `member` in Keycloak (an
    -- admin who also writes notes), so it does not exercise the pure
    -- admin view. Log in as this one to see it: no notes, no dictations
    -- — only the workspace roster and settings.
    ('0b000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000a', 'owner@tenant-a.example',   'Dev Owner A',   'tenant_admin', 'active'),
    ('0c000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'member@tenant-a.example',  'Dev Member A',  'member',       'active'),
    ('0d000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'viewer@tenant-a.example',  'Dev Viewer A',  'viewer',       'active'),
    ('0e000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'auditor@tenant-a.example', 'Dev Auditor A', 'auditor',      'active'),
    ('0c000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000b', 'member@tenant-b.example',  'Dev Member B',  'member',       'active'),
    ('0a000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000b', 'admin@tenant-b.example',   'Dev Admin B',   'tenant_admin', 'active')
-- Conflict on (tenant_id, email), NOT on sub. The subs above are only correct
-- on a stack whose Keycloak was built from realm-export.json: Keycloak honours
-- a caller-supplied user id during realm import but NOT via its admin REST API,
-- which silently mints its own (verified on KC 24). So any account created by
-- hand on a running stack carries a different sub for the same email, and
-- conflicting on sub made this INSERT try to add a second row for that email —
-- violating users_tenant_id_email_key and aborting the whole seed. Keying on
-- the email keeps whichever sub the live Keycloak issued (the authoritative
-- one, since it is what the token carries) and refreshes the mutable columns.
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

-- ── Tenant memberships ──────────────────────────────────────────────────────
-- Fresh dev DBs seed users here (after migrations); create the memberships
-- explicitly, mapping the platform role to the management role. Idempotent
-- on (tenant_id, user_sub).
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

-- Cross-tenant demo: let Dev Admin A also administer tenant-B as an admin, so
-- the workspace switcher / members UI has multi-tenant data to exercise.
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
VALUES ('00000000-0000-0000-0000-00000000000b', '0a000000-0000-0000-0000-00000000000a', 'admin', 'active')
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Example workspace "Sunrise Studio" owned by the current login account ───
-- A fully-branded example workspace, with Dev Admin A
-- (admin@tenant-a.example — the account used to log in now) linked as its
-- owner. It shows up in that account's workspace switcher (GET /tenants)
-- and workspace-settings page.
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

-- Link the current login account (Dev Admin A) to the example workspace.
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
VALUES ('0000c111-0000-0000-0000-000000000001', '0a000000-0000-0000-0000-00000000000a', 'owner', 'active')
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Notes AI's own account — the vendor, not a customer ────────────────────
-- Backs the platform-owner console at #/company (src/company/ in the SPA),
-- whose access gate is an email allowlist because there is no platform role
-- in KNOWN_ROLES yet. In Keycloak it carries tenant_admin + auditor:
-- tenant_admin covers /admin/users and /tenants/*, auditor covers /audit/*,
-- and the Usage tab's notes/sessions/ASR reads resolve through
-- tenant_admin's `stats.read` in the content-stripped mode. Anchored in
-- tenant-a so the token's tid points at the tenant that has seeded
-- activity.
--
-- Reconciled on email, not on a pinned sub, for the same Keycloak reason
-- documented on the users INSERT above.
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

-- ── Notes AI owner: member of every tenant ─────────────────────────────────
-- The platform-owner console reads its portfolio from GET /tenants, which
-- returns exactly the tenants the caller is a MEMBER of. The cross join is
-- deliberate: every tenant seeded here and any added later gets a
-- membership, so the console never silently misses a workspace. Keyed off
-- the email because the sub is whatever the live Keycloak issued.
-- Idempotent on (tenant_id, user_sub).
INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
SELECT t.id, u.sub, 'owner', 'active'
FROM tenants t
CROSS JOIN users u
WHERE u.email = 'vpu2301@gmail.com'
ON CONFLICT (tenant_id, user_sub) DO NOTHING;

-- ── Identities for every seeded user ──────────────────────────────────────
-- Migration 0028 repointed notes.primary_author_id, note_versions.created_by
-- and autocomplete_*.owner_user_id from users(sub) to identities(id). The
-- 0027 backfill only sees the users that existed WHEN IT RAN, and on a fresh
-- stack that is none — migrations run against an empty database and the seed
-- lands afterwards. So a seeded account signed in fine and then 500'd on
-- every POST /v1/notes with notes_primary_author_id_fkey: "Key is not present
-- in table identities".
--
-- Same shape as 0027's backfill, keyed off users so it stays correct when
-- Keycloak issued a sub of its own (see the users INSERT above). legacy_idp
-- is true: these accounts authenticate through Keycloak, their password and
-- MFA live there, and ADR-0047's dual mode has to know that.
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

-- Keep the profile in step on re-seed. The INSERT above only fires for an
-- identity that does not exist yet, so without this a display name edited
-- in the users INSERT lands on `users` and never reaches `identities` —
-- the seed then reports one name and every native token carries the other.
--
-- Scoped to legacy_idp: for a Keycloak-backed identity the profile is
-- owned upstream and `users` is the local mirror of it, so copying down is
-- correct. A native identity (IDX-BE-3) owns its own name and must never
-- have it overwritten by a seed run.
UPDATE identities i
SET display_name = u.display_name
FROM users u
WHERE u.sub = i.id
  AND i.legacy_idp
  AND i.display_name IS DISTINCT FROM u.display_name;

COMMIT;
