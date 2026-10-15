-- 0071 — Workspace role vocabulary (W1, ADR-0069). `guest` joins the
-- membership roles so every client and RLS path can carry it before W3
-- offers it; `assistant` stays only so existing rows remain valid.
--
-- "One personal workspace per identity" cannot be a partial unique index
-- (the predicate would need `tenants.kind`), and copying `kind` onto the
-- membership row would drift. It is enforced by
-- `IdentityRepository.ensure_personal_workspace` and checked by
-- `scripts/ci/check-identity-bridge.py`.
ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check
    CHECK (role IN ('owner', 'admin', 'member', 'viewer', 'guest', 'assistant'));   -- assistant: legacy, never offered

COMMENT ON COLUMN tenant_memberships.role IS
    'owner|admin|member|viewer|guest; assistant is legacy (W1)';
COMMENT ON COLUMN tenants.kind IS
    'personal: exactly one per identity, owner membership only, never dissolved (invariant enforced by ensure_personal_workspace + scripts/ci/check-identity-bridge.py)';
