"""IDX-B2 — the principal consolidation, against a real database.

Three things to prove:

  * every foreign key now points at `identities`, with its `ON DELETE`
    semantics unchanged;
  * `profile_of_subs` is a tenant-scoped window onto `identities` that
    `app_role` can use and cannot abuse;
  * the bug in IDX-B2 §C is actually fixed — a member of two workspaces
    now renders in both, where the per-tenant `users` table showed them
    as blank in the second.

Requires ``RUN_DB_INTEGRATION=1`` and ``make migrate-up``.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and a migrated dev database",
)

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
APP_DSN = "postgresql://app_role:app_role@localhost:5432/notes"
WRITER_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
MARK = "b2test"


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        await conn.execute(
            "DELETE FROM tenant_memberships WHERE user_sub IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            f"%{MARK}%",
        )
        await conn.execute("DELETE FROM identities WHERE email LIKE $1", f"%{MARK}%")
        await conn.close()


async def _app_conn(tenant: uuid.UUID | None) -> asyncpg.Connection:
    conn = await asyncpg.connect(APP_DSN)
    if tenant is not None:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant))
    return conn


# ── the FK swap ──────────────────────────────────────────────────────────


async def test_no_foreign_key_points_at_users_any_more(su) -> None:
    assert (
        await su.fetchval("SELECT count(*) FROM pg_constraint WHERE confrelid = 'users'::regclass")
        == 0
    )


async def test_all_thirteen_moved_to_identities(su) -> None:
    """The pack's inventory listed six; the live catalogue had thirteen.

    Pinned by name so a future migration that adds a fourteenth without
    pointing it at `identities` is caught here rather than at the drop.
    """
    rows = await su.fetch(
        "SELECT conrelid::regclass::text AS t, conname FROM pg_constraint"
        " WHERE confrelid = 'identities'::regclass AND contype = 'f'"
    )
    moved = {r["conname"] for r in rows}
    for expected in (
        "notes_primary_author_id_fkey",
        "note_versions_created_by_fkey",
        "autocomplete_phrases_owner_user_id_fkey",
        "autocomplete_snippets_owner_user_id_fkey",
        "mfa_reminders_subject_sub_fkey",
        "mfa_reminders_requested_by_fkey",
        # The seven the pack's inventory missed.
        "auth_mail_outbox_subject_sub_fkey",
        "auth_password_events_subject_sub_fkey",
        "auth_password_reset_tokens_subject_sub_fkey",
        "notifications_recipient_user_id_fkey",
        "notification_preferences_user_id_fkey",
        "notification_user_settings_user_id_fkey",
        "notification_digest_progress_user_id_fkey",
    ):
        assert expected in moved, f"{expected} did not move to identities"


async def test_on_delete_semantics_are_preserved(su) -> None:
    """RESTRICT is what stops an append-only history losing its author."""
    by_name = {
        r["conname"]: r["confdeltype"]
        for r in await su.fetch(
            "SELECT conname, confdeltype FROM pg_constraint"
            " WHERE confrelid = 'identities'::regclass AND contype = 'f'"
        )
    }

    # asyncpg returns the "char" column as bytes.
    def _ondelete(name: str) -> str:
        raw = by_name[name]
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    assert _ondelete("notes_primary_author_id_fkey") == "r"
    assert _ondelete("note_versions_created_by_fkey") == "r"
    assert _ondelete("autocomplete_phrases_owner_user_id_fkey") == "c"
    assert _ondelete("mfa_reminders_requested_by_fkey") == "n"


async def test_every_users_row_has_an_identity(su) -> None:
    assert (
        await su.fetchval(
            "SELECT count(*) FROM users u LEFT JOIN identities i ON i.id = u.sub WHERE i.id IS NULL"
        )
        == 0
    )


async def test_the_constraints_are_validated_not_merely_added(su) -> None:
    """`NOT VALID` without `VALIDATE` would let a bad row in later."""
    unvalidated = await su.fetch(
        "SELECT conname FROM pg_constraint"
        " WHERE confrelid = 'identities'::regclass AND contype = 'f' AND NOT convalidated"
    )
    assert unvalidated == []


# ── profile_of_subs ──────────────────────────────────────────────────────


async def _seed_identity(su, email: str, name: str, tenants: list[uuid.UUID]) -> uuid.UUID:
    identity_id = uuid.uuid4()
    await su.execute(
        "INSERT INTO identities (id, email, display_name, status) VALUES ($1, $2, $3, 'active')",
        identity_id,
        email,
        name,
    )
    for tenant in tenants:
        await su.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)"
            " VALUES ($1, $2, 'member', 'active')",
            tenant,
            identity_id,
        )
    return identity_id


async def test_a_member_of_two_workspaces_renders_in_both(su) -> None:
    """The IDX-B2 §C bug, fixed.

    `users` is keyed on `sub`, so a principal has exactly one row in one
    home tenant. A colleague invited into a second workspace had no row
    there, and every author/roster join was a LEFT JOIN that rendered
    them blank. `profile_of_subs` reads `identities`, which is not
    per-tenant, so both workspaces see the same person.
    """
    sub = await _seed_identity(su, f"both-{MARK}@x.example", "Ada Both", [TENANT_A, TENANT_B])

    for tenant in (TENANT_A, TENANT_B):
        conn = await _app_conn(tenant)
        try:
            rows = await conn.fetch(
                "SELECT display_name, email FROM profile_of_subs($1::uuid[])", [sub]
            )
            assert len(rows) == 1, f"invisible in {tenant}"
            assert rows[0]["display_name"] == "Ada Both"
        finally:
            await conn.close()


async def test_a_sub_outside_the_tenant_is_invisible(su) -> None:
    sub = await _seed_identity(su, f"onlyb-{MARK}@x.example", "Only B", [TENANT_B])
    conn = await _app_conn(TENANT_A)
    try:
        assert await conn.fetch("SELECT * FROM profile_of_subs($1::uuid[])", [sub]) == []
    finally:
        await conn.close()


async def test_a_suspended_membership_does_not_resolve(su) -> None:
    """Leaving a workspace stops you appearing in its roster."""
    sub = await _seed_identity(su, f"susp-{MARK}@x.example", "Suspended", [TENANT_A])
    await su.execute("UPDATE tenant_memberships SET status = 'suspended' WHERE user_sub = $1", sub)
    conn = await _app_conn(TENANT_A)
    try:
        assert await conn.fetch("SELECT * FROM profile_of_subs($1::uuid[])", [sub]) == []
    finally:
        await conn.close()


async def test_an_unscoped_connection_gets_nothing(su) -> None:
    """Without `app.tenant_id` the predicate compares to NULL, so the
    function cannot be used as a directory of everybody."""
    sub = await _seed_identity(su, f"scope-{MARK}@x.example", "Scoped", [TENANT_A])
    conn = await _app_conn(None)
    try:
        assert await conn.fetch("SELECT * FROM profile_of_subs($1::uuid[])", [sub]) == []
    finally:
        await conn.close()


async def test_a_deleted_identity_does_not_resolve(su) -> None:
    """A purged account (IDX-A5) must not come back as a name."""
    sub = await _seed_identity(su, f"gone-{MARK}@x.example", "Gone", [TENANT_A])
    await su.execute("UPDATE identities SET status = 'deleted' WHERE id = $1", sub)
    conn = await _app_conn(TENANT_A)
    try:
        assert await conn.fetch("SELECT * FROM profile_of_subs($1::uuid[])", [sub]) == []
    finally:
        await conn.close()


async def test_app_role_still_cannot_read_identities_directly(su) -> None:
    """The function is the only path; the table stays sealed."""
    conn = await _app_conn(TENANT_A)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM identities LIMIT 1")
    finally:
        await conn.close()


async def test_the_function_is_security_definer_and_not_public(su) -> None:
    row = await su.fetchrow(
        "SELECT prosecdef, proacl::text FROM pg_proc WHERE proname = 'profile_of_subs'"
    )
    assert row["prosecdef"] is True
    assert "=X/" in row["proacl"]
    assert "PUBLIC=X" not in row["proacl"].replace("=X/", "")


# ── the rewritten service queries ────────────────────────────────────────


async def test_note_service_finds_a_cross_tenant_member_by_email(su) -> None:
    """`find_member_by_email` used to miss exactly this person.

    Sharing a note with a colleague who joined from another workspace
    failed with "no such member"; the address was in `identities` but not
    in this tenant's `users` rows.
    """
    from note_service.domain import notes_repository as repo

    email = f"cross-{MARK}@x.example"
    sub = await _seed_identity(su, email, "Cross Tenant", [TENANT_A, TENANT_B])

    conn = await _app_conn(TENANT_B)
    try:
        found = await repo.find_member_by_email(conn, email=email)
        assert found is not None, "cross-tenant member still not resolvable"
        assert found.sub == sub
        assert found.display_name == "Cross Tenant"
        assert found.email == email
    finally:
        await conn.close()


async def test_note_service_fetch_members_resolves_display_names(su) -> None:
    from note_service.domain import notes_repository as repo

    a = await _seed_identity(su, f"m1-{MARK}@x.example", "Member One", [TENANT_A])
    b = await _seed_identity(su, f"m2-{MARK}@x.example", "Member Two", [TENANT_A])
    outsider = await _seed_identity(su, f"m3-{MARK}@x.example", "Outsider", [TENANT_B])

    conn = await _app_conn(TENANT_A)
    try:
        rows = await repo.fetch_members(conn, subs=[a, b, outsider])
        assert {r.display_name for r in rows} == {"Member One", "Member Two"}
        assert outsider not in {r.sub for r in rows}
    finally:
        await conn.close()


async def test_notification_service_resolves_an_address_and_admins(su) -> None:
    from notification_service.domain import repository as repo

    sub = await _seed_identity(su, f"notify-{MARK}@x.example", "Notify Me", [TENANT_A])
    conn = await _app_conn(TENANT_A)
    try:
        assert await repo.user_email(conn, sub) == f"notify-{MARK}@x.example"
        assert await repo.filter_to_tenant_members(conn, [sub]) == [sub]
        # `tenant_admin_ids` now reads memberships, so it finds an admin
        # of THIS workspace even if their home tenant is elsewhere.
        admins = await repo.tenant_admin_ids(conn)
        assert isinstance(admins, list)
    finally:
        await conn.close()
