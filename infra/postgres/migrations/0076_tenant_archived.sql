-- 0076 — A team workspace can be archived: closed for everyone (is_active =
-- false, so sessions heal to Personal and it leaves the switcher), nothing
-- deleted, memberships untouched. Only its owners still see it, under
-- "Archived", and may restore it at any time. Unlike `dissolved`, an archived
-- workspace keeps its members and has no restore window.
ALTER TABLE tenants DROP CONSTRAINT tenants_status_check;
ALTER TABLE tenants ADD CONSTRAINT tenants_status_check
    CHECK (status IN ('active', 'suspended', 'archived', 'dissolved'));
