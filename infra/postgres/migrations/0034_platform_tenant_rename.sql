-- 0034 — rename the platform tenant's display name to the product's own.
--
-- 0024 seeded the platform tenant as 'Klarnote Platform'. That name never
-- belonged to this product — it leaked in from a sibling project during
-- the IDX identity sprints and got copied across email copy, config
-- defaults and the realm export. Everything else was corrected in place;
-- this row could not be, because 0024 is applied everywhere and
-- `scripts/db/migrate.py` aborts on checksum drift for an applied file.
-- So the correction arrives as its own migration instead.
--
-- Matched on the pinned id, not on the old string: the id is the stable
-- thing (0024 pins it so `AUTH_PLATFORM_TENANT_ID` has a working default),
-- and a database that already carries the right name is then simply a
-- no-op rather than a silent miss.
UPDATE tenants
SET display_name = 'Notes AI Platform'
WHERE id = '00000000-0000-0000-0000-0000000000f1';
