-- Reverses 0034. Cosmetic only: the platform tenant is the home for audit
-- events that belong to no customer, and nothing keys off its display name.
UPDATE tenants
SET display_name = 'Klarnote Platform'
WHERE id = '00000000-0000-0000-0000-0000000000f1';
