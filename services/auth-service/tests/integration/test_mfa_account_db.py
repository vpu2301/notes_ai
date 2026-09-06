"""IDX-A5 against a real Postgres and a real envelope.

What only the database and libs/crypto can prove:

  * a TOTP secret in the column is AES-GCM ciphertext, not base32;
  * the step claim is a conditional UPDATE, so concurrent uses of one code
    produce exactly one winner;
  * a recovery code is spent once under concurrency;
  * the sole-owner rule sees the real membership graph;
  * deletion dissolves solo workspaces and leaves shared ones alone;
  * the purge crypto-shreds credentials and frees the address.

Requires: ``RUN_DB_INTEGRATION=1``, ``make migrate-up``, and the dev
master key at ``infra/dev/master.key``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and a migrated dev database",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("MDX_MASTER_KEY_PATH", "infra/dev/master.key")

from auth_service import totp  # noqa: E402
from auth_service.domain import mfa  # noqa: E402
from auth_service.domain.identity_repository import (  # noqa: E402
    IdentityRepository,
    RecoveryCodeRepository,
    SessionRepository,
    TotpRepository,
)
from auth_service.domain.identity_secrets import EnvelopeSecretBox  # noqa: E402
from crypto import DecryptError  # noqa: E402

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
WRITER_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"
PLATFORM = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
DOMAIN = "a5.example"


def _email() -> str:
    return f"m{uuid.uuid4().hex[:12]}@{DOMAIN}"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(WRITER_DSN, min_size=1, max_size=6)
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        like = f"%@{DOMAIN}"
        ids = "(SELECT id FROM identities WHERE email LIKE $1 OR email LIKE 'deleted:%')"
        await conn.execute(f"DELETE FROM identity_totp WHERE identity_id IN {ids}", like)
        await conn.execute(f"DELETE FROM identity_recovery_codes WHERE identity_id IN {ids}", like)
        await conn.execute(f"DELETE FROM auth_challenges WHERE identity_id IN {ids}", like)
        await conn.execute(f"DELETE FROM auth_sessions WHERE identity_id IN {ids}", like)
        await conn.execute(
            f"DELETE FROM users WHERE tenant_id IN (SELECT tenant_id FROM tenant_memberships"
            f" WHERE user_sub IN {ids})",
            like,
        )
        await conn.execute(
            f"DELETE FROM tenants WHERE id IN (SELECT tenant_id FROM tenant_memberships"
            f" WHERE user_sub IN {ids})",
            like,
        )
        await conn.execute(
            "DELETE FROM identities WHERE email LIKE $1 OR email LIKE 'deleted:%'", like
        )
        await conn.close()


@pytest_asyncio.fixture
async def envelope():
    from crypto import Envelope, TenantKekRepository, build_master_key_provider
    from db import create_pool

    master = build_master_key_provider(
        provider="file",
        file_path="infra/dev/master.key",
        vault_addr="",
        vault_token=None,
        vault_transit_key="",
        vault_transit_mount="",
    )
    await master.startup_self_check()
    crypto_pool = await create_pool(
        "postgresql://crypto_writer:crypto_writer@localhost:5432/notes",
        application_name="a5-test",
    )
    try:
        yield Envelope(
            master_key_provider=master,
            kek_repository=TenantKekRepository(pool=crypto_pool, master_key_provider=master),
        )
    finally:
        await crypto_pool.close()


@pytest_asyncio.fixture
async def box(envelope):
    async def _provider():
        return envelope

    return EnvelopeSecretBox(envelope_provider=_provider, kek_tenant_id=PLATFORM)


# ── the secret at rest ───────────────────────────────────────────────────


async def test_the_stored_totp_secret_is_ciphertext_not_base32(pool, su, box) -> None:
    """The acceptance criterion, read straight off the column."""
    repo = IdentityRepository(pool)
    store = TotpRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())

    secret = totp.generate_secret()
    sealed, kek_tenant = await box.seal(secret=secret, identity_id=identity.id)
    await store.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek_tenant)

    stored = await su.fetchval(
        "SELECT secret_enc FROM identity_totp WHERE identity_id = $1", identity.id
    )
    assert secret not in stored
    # Not a base32 secret by any reading of it — the acceptance criterion
    # asks for exactly this check against the column.
    with pytest.raises(binascii.Error):
        base64.b32decode(stored + "=" * (-len(stored) % 8), casefold=True)

    # ...and it round-trips through the envelope.
    assert (
        await box.open(sealed=stored, identity_id=identity.id, kek_tenant_id=kek_tenant) == secret
    )


async def test_a_secret_cannot_be_opened_as_another_identitys(pool, box) -> None:
    """The AAD binds the blob to its row: a copied ciphertext is inert."""
    repo = IdentityRepository(pool)
    a, _ = await repo.create_with_personal_workspace(_email())
    b, _ = await repo.create_with_personal_workspace(_email())
    sealed, kek = await box.seal(secret=totp.generate_secret(), identity_id=a.id)
    with pytest.raises(DecryptError):
        await box.open(sealed=sealed, identity_id=b.id, kek_tenant_id=kek)


# ── step accounting ──────────────────────────────────────────────────────


async def test_a_time_step_is_claimed_exactly_once(pool, box) -> None:
    repo = IdentityRepository(pool)
    store = TotpRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    sealed, kek = await box.seal(secret=totp.generate_secret(), identity_id=identity.id)
    await store.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek)
    assert await store.confirm(identity.id, step=100)

    # Ten simultaneous uses of the same code: one wins.
    results = await asyncio.gather(*(store.spend_step(identity.id, step=101) for _ in range(10)))
    assert sum(results) == 1
    # An older step never wins, a newer one does.
    assert not await store.spend_step(identity.id, step=100)
    assert await store.spend_step(identity.id, step=102)


async def test_an_unconfirmed_secret_gates_nothing(pool, box) -> None:
    """An abandoned enrolment must not lock anyone out."""
    repo = IdentityRepository(pool)
    store = TotpRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    sealed, kek = await box.seal(secret=totp.generate_secret(), identity_id=identity.id)
    await store.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek)

    record = await store.get(identity.id)
    assert record is not None and record.confirmed_at is None
    # spend_step refuses while unconfirmed.
    assert not await store.spend_step(identity.id, step=500)


async def test_confirming_twice_does_not_reset_the_step_counter(pool, box) -> None:
    repo = IdentityRepository(pool)
    store = TotpRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    sealed, kek = await box.seal(secret=totp.generate_secret(), identity_id=identity.id)
    await store.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek)
    assert await store.confirm(identity.id, step=900)
    assert not await store.confirm(identity.id, step=1)
    record = await store.get(identity.id)
    assert record is not None and record.last_used_step == 900


# ── recovery codes ───────────────────────────────────────────────────────


async def test_a_recovery_code_is_spent_once_under_concurrency(pool) -> None:
    repo = IdentityRepository(pool)
    recovery = RecoveryCodeRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())

    codes = mfa.generate_recovery_codes()
    await recovery.replace_all(identity.id, hashes=[mfa.recovery_code_hash(c) for c in codes])
    assert await recovery.count_unused(identity.id) == 10

    digest = mfa.recovery_code_hash(codes[0])
    results = await asyncio.gather(
        *(recovery.consume(identity.id, code_hash=digest) for _ in range(5))
    )
    assert sum(results) == 1
    assert await recovery.count_unused(identity.id) == 9
    assert not await recovery.consume(identity.id, code_hash=digest)


async def test_regenerating_invalidates_every_old_code(pool) -> None:
    repo = IdentityRepository(pool)
    recovery = RecoveryCodeRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    old = mfa.generate_recovery_codes()
    await recovery.replace_all(identity.id, hashes=[mfa.recovery_code_hash(c) for c in old])
    new = mfa.generate_recovery_codes()
    await recovery.replace_all(identity.id, hashes=[mfa.recovery_code_hash(c) for c in new])

    assert await recovery.count_unused(identity.id) == 10
    assert not await recovery.consume(identity.id, code_hash=mfa.recovery_code_hash(old[0]))
    assert await recovery.consume(identity.id, code_hash=mfa.recovery_code_hash(new[0]))


# ── sessions ─────────────────────────────────────────────────────────────


async def test_sessions_list_revoke_and_spare_the_current_one(pool) -> None:
    repo = IdentityRepository(pool)
    sessions = SessionRepository(pool)
    identity, membership = await repo.create_with_personal_workspace(_email())

    made = []
    for agent in ("Macintosh", "iPhone", "Windows"):
        sid, _ = await sessions.create(
            identity_id=identity.id,
            tenant_id=membership.tenant_id,
            refresh_token=uuid.uuid4().hex,
            ttl_seconds=3600,
            client_type="web",
            ip="203.0.113.7",
            user_agent=agent,
            device_name=agent,
        )
        made.append(sid)

    assert len(await sessions.list_live(identity.id)) == 3

    revoked = await sessions.revoke_all(
        identity.id, reason="revoke_others", except_session_id=made[0]
    )
    assert set(revoked) == set(made[1:])
    live = await sessions.list_live(identity.id)
    assert [s.id for s in live] == [made[0]]


async def test_a_session_belonging_to_someone_else_cannot_be_revoked(pool) -> None:
    repo = IdentityRepository(pool)
    sessions = SessionRepository(pool)
    mine, my_ws = await repo.create_with_personal_workspace(_email())
    theirs, their_ws = await repo.create_with_personal_workspace(_email())
    their_sid, _ = await sessions.create(
        identity_id=theirs.id,
        tenant_id=their_ws.tenant_id,
        refresh_token=uuid.uuid4().hex,
        ttl_seconds=3600,
        client_type="web",
        ip="",
        user_agent="",
    )
    assert not await sessions.revoke(their_sid, identity_id=mine.id, reason="user_revoked")
    assert len(await sessions.list_live(theirs.id)) == 1


async def test_step_up_stamps_the_session(pool) -> None:
    repo = IdentityRepository(pool)
    sessions = SessionRepository(pool)
    identity, membership = await repo.create_with_personal_workspace(_email())
    sid, _ = await sessions.create(
        identity_id=identity.id,
        tenant_id=membership.tenant_id,
        refresh_token=uuid.uuid4().hex,
        ttl_seconds=3600,
        client_type="web",
        ip="",
        user_agent="",
    )
    before = (await sessions.get(sid)).last_authenticated_at
    await asyncio.sleep(0.01)
    await sessions.touch_authenticated(sid)
    assert (await sessions.get(sid)).last_authenticated_at > before


# ── email change ─────────────────────────────────────────────────────────


async def test_changing_the_email_moves_the_login_and_the_users_rows(pool, su) -> None:
    repo = IdentityRepository(pool)
    identity, membership = await repo.create_with_personal_workspace(_email())
    new = _email()

    updated = await repo.change_email(identity.id, new_email=new)
    assert updated is not None and updated.email == new
    assert updated.email_verified_at is not None
    # The rest of the estate resolves a sub through `users`; it must move too.
    assert await su.fetchval("SELECT email FROM users WHERE sub = $1", identity.id) == new
    assert await repo.email_is_taken(new)
    assert not await repo.email_is_taken(identity.email)
    del membership


async def test_a_pending_deletion_address_is_still_taken(pool) -> None:
    """It is still theirs until the purge; signing in reclaims the account."""
    repo = IdentityRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    await repo.request_deletion(identity.id)
    assert await repo.email_is_taken(identity.email)


# ── deletion ─────────────────────────────────────────────────────────────


async def test_deleting_dissolves_a_solo_workspace(pool, su) -> None:
    repo = IdentityRepository(pool)
    identity, membership = await repo.create_with_personal_workspace(_email())

    assert await repo.sole_owner_tenants_with_members(identity.id) == []
    dissolved = await repo.request_deletion(identity.id)
    assert dissolved == [membership.tenant_id]

    row = await su.fetchrow(
        "SELECT status, is_active FROM tenants WHERE id = $1", membership.tenant_id
    )
    assert row["status"] == "dissolved" and row["is_active"] is False
    fresh = await repo.get(identity.id)
    assert fresh is not None
    assert fresh.status == "pending_deletion"
    assert fresh.deletion_requested_at is not None


async def test_the_only_owner_of_a_shared_workspace_is_refused(pool, su) -> None:
    repo = IdentityRepository(pool)
    owner, membership = await repo.create_with_personal_workspace(_email())
    colleague, _ = await repo.create_with_personal_workspace(_email())
    # Put the colleague in the owner's workspace as a member.
    await su.execute(
        "INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)"
        " VALUES ($1, $2, 'member', 'active')",
        membership.tenant_id,
        colleague.id,
    )

    blocking = await repo.sole_owner_tenants_with_members(owner.id)
    assert [m.tenant_id for m in blocking] == [membership.tenant_id]
    # The colleague is not an owner anywhere shared, so they may leave.
    assert await repo.sole_owner_tenants_with_members(colleague.id) == []


async def test_a_second_owner_unblocks_deletion(pool, su) -> None:
    repo = IdentityRepository(pool)
    owner, membership = await repo.create_with_personal_workspace(_email())
    other, _ = await repo.create_with_personal_workspace(_email())
    await su.execute(
        "INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)"
        " VALUES ($1, $2, 'owner', 'active')",
        membership.tenant_id,
        other.id,
    )
    assert await repo.sole_owner_tenants_with_members(owner.id) == []


# ── purge ────────────────────────────────────────────────────────────────


async def test_the_purge_shreds_credentials_and_frees_the_address(pool, su, box) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts" / "ops"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "purge",
        Path(__file__).resolve().parents[4] / "scripts" / "ops" / "idx-purge-deleted-identities.py",
    )
    assert spec and spec.loader
    purge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(purge)

    repo = IdentityRepository(pool)
    store = TotpRepository(pool)
    recovery = RecoveryCodeRepository(pool)
    identity, membership = await repo.create_with_personal_workspace(_email())
    original_email = identity.email

    sealed, kek = await box.seal(secret=totp.generate_secret(), identity_id=identity.id)
    await store.put_candidate(identity.id, secret_enc=sealed, kek_tenant_id=kek)
    await store.confirm(identity.id, step=1)
    await recovery.replace_all(
        identity.id, hashes=[mfa.recovery_code_hash(c) for c in mfa.generate_recovery_codes()]
    )
    await repo.request_deletion(identity.id)

    conn = await asyncpg.connect(WRITER_DSN)
    try:
        await purge.purge_one(conn, identity.id)
    finally:
        await conn.close()

    row = await su.fetchrow(
        "SELECT email, display_name, password_hash, mfa_enabled, status"
        " FROM identities WHERE id = $1",
        identity.id,
    )
    assert row["email"] == f"deleted:{identity.id}"
    assert row["status"] == "deleted"
    assert row["password_hash"] is None
    assert row["mfa_enabled"] is False
    # Credentials are gone entirely, not merely unusable.
    assert (
        await su.fetchval("SELECT count(*) FROM identity_totp WHERE identity_id = $1", identity.id)
        == 0
    )
    assert (
        await su.fetchval(
            "SELECT count(*) FROM identity_recovery_codes WHERE identity_id = $1", identity.id
        )
        == 0
    )
    # The address is free for somebody else to register.
    assert not await repo.email_is_taken(original_email)
    del membership


async def test_the_purge_is_idempotent(pool, su) -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "purge2",
        Path(__file__).resolve().parents[4] / "scripts" / "ops" / "idx-purge-deleted-identities.py",
    )
    assert spec and spec.loader
    purge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(purge)

    repo = IdentityRepository(pool)
    identity, _ = await repo.create_with_personal_workspace(_email())
    await repo.request_deletion(identity.id)
    conn = await asyncpg.connect(WRITER_DSN)
    try:
        await purge.purge_one(conn, identity.id)
        await purge.purge_one(conn, identity.id)  # a re-run must not blow up
    finally:
        await conn.close()
    assert (
        await su.fetchval("SELECT email FROM identities WHERE id = $1", identity.id)
        == f"deleted:{identity.id}"
    )
