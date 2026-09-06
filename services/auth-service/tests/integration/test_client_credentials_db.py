"""IDX-B1b against a real Postgres and Redis.

The properties only the database and the cache can prove: that a secret
for one credential cannot open another, that the lock is fail-closed,
that rotation gives two live secrets and then one, that `app_role` cannot
read a hash, and that one workspace's rooms are invisible from another's.

Requires ``RUN_DB_INTEGRATION=1``, ``make migrate-up``, and the dev
stack's Postgres and Redis.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from auth_service.adapters.client_lock import (  # noqa: E402
    LockUnavailableError,
    RedisClientLock,
)
from auth_service.domain import credentials as cred  # noqa: E402
from auth_service.domain.credential_repository import CredentialRepository  # noqa: E402
from auth_service.domain.credential_service import (  # noqa: E402
    CredentialError,
    CredentialService,
)
from auth_service.domain.signing_keys import KeySet  # noqa: E402
from auth_service.domain.token_service import TokenService  # noqa: E402

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
WRITER_DSN = "postgresql://tenant_writer:tenant_writer@localhost:5432/notes"
APP_DSN = "postgresql://app_role:app_role@localhost:5432/notes"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
PLATFORM = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
MARK = "b1btest"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(WRITER_DSN, min_size=1, max_size=5)
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
        await conn.execute("DELETE FROM service_credentials WHERE name LIKE $1", f"%{MARK}%")
        await conn.close()


@pytest_asyncio.fixture
async def redis():
    import redis.asyncio as aioredis

    client = aioredis.from_url("redis://localhost:6379/0", decode_responses=False)
    try:
        yield client
    finally:
        keys = [k async for k in client.scan_iter("mdx:auth:*client*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


@pytest_asyncio.fixture
async def service(pool, redis):
    from pathlib import Path

    keys = KeySet.from_json(
        (
            Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"
        ).read_text()
    )
    from ratelimit import FixedWindowLimiter

    return CredentialService(
        repo=CredentialRepository(pool),
        tokens=TokenService(
            keys=keys,
            issuer="http://localhost:8000",
            audience="mdx-api",
            access_ttl_seconds=900,
        ),
        limiter=FixedWindowLimiter(redis, prefix="mdx:auth:rl"),
        lock=RedisClientLock(redis, threshold=10, window_seconds=600, lock_seconds=900),
        denylist=None,
        platform_tenant_id=PLATFORM,
        revoked_ttl_seconds=1200,
    )


def _name(what: str) -> str:
    return f"{MARK}-{what}-{uuid.uuid4().hex[:8]}"


# ── the grant ────────────────────────────────────────────────────────────


async def test_a_device_token_carries_its_rows_tenant(service, su) -> None:
    from jose import jwt

    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    issued = await service.issue_token(
        client_id=str(created.credential.id), client_secret=created.secret, ip="203.0.113.7"
    )
    payload = jwt.get_unverified_claims(issued.access_token)
    assert payload["tid"] == str(TENANT_A)
    assert payload["roles"] == ["device"]
    assert payload["sub"] == str(created.credential.id)
    assert issued.expires_in == 900
    # last_used_at is stamped, so an operator can see the room checking in.
    row = await su.fetchrow(
        "SELECT last_used_at FROM service_credentials WHERE id = $1", created.credential.id
    )
    assert row["last_used_at"] is not None


async def test_a_service_token_is_minted_against_the_platform_tenant(service) -> None:
    """`Claims.tid` is required and a service credential has no workspace.

    The platform tenant owns no customer data, so a leaked service token
    reaches nothing — the right default for a principal nobody has scoped.
    """
    from jose import jwt

    created = await service.create(
        kind="service", tenant_id=None, name=_name("svc"), created_by=None
    )
    issued = await service.issue_token(
        client_id=str(created.credential.id), client_secret=created.secret, ip=""
    )
    payload = jwt.get_unverified_claims(issued.access_token)
    assert payload["tid"] == str(PLATFORM)
    assert payload["roles"] == ["service"]


async def test_every_bad_grant_answers_identically(service) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    other = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room2"), created_by=None
    )
    bodies = []
    for client_id, secret in (
        (str(uuid.uuid4()), created.secret),  # unknown client
        (str(created.credential.id), other.secret),  # someone else's secret
        (str(created.credential.id), cred.generate_secret().value),  # wrong secret
        ("not-a-uuid", created.secret),  # malformed id
    ):
        with pytest.raises(CredentialError) as exc:
            await service.issue_token(client_id=client_id, client_secret=secret, ip="")
        bodies.append((exc.value.code, exc.value.status_code, exc.value.detail))
    assert len(set(bodies)) == 1, "every failure must be indistinguishable"
    assert bodies[0][:2] == ("invalid_client", 401)


async def test_a_secret_cannot_be_used_under_another_credentials_id(service) -> None:
    """The lookup is by hash alone, so this check is what binds them."""
    a = await service.create(kind="device", tenant_id=TENANT_A, name=_name("a"), created_by=None)
    b = await service.create(kind="device", tenant_id=TENANT_B, name=_name("b"), created_by=None)
    with pytest.raises(CredentialError):
        await service.issue_token(client_id=str(b.credential.id), client_secret=a.secret, ip="")


async def test_a_revoked_credential_stops_immediately(service) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    await service.issue_token(
        client_id=str(created.credential.id), client_secret=created.secret, ip=""
    )
    await service.revoke(created.credential.id)
    with pytest.raises(CredentialError) as exc:
        await service.issue_token(
            client_id=str(created.credential.id), client_secret=created.secret, ip=""
        )
    assert exc.value.code == "invalid_client"


# ── lock ─────────────────────────────────────────────────────────────────


async def test_ten_wrong_secrets_lock_the_client(service) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    cid = str(created.credential.id)
    wrong = cred.generate_secret().value

    for _ in range(9):
        with pytest.raises(CredentialError) as exc:
            await service.issue_token(client_id=cid, client_secret=wrong, ip="")
        assert exc.value.code == "invalid_client"

    # The tenth failure trips the lock and says so, once.
    with pytest.raises(CredentialError) as exc:
        await service.issue_token(client_id=cid, client_secret=wrong, ip="")
    assert exc.value.tripped_lock is True

    # And the correct secret is now refused too — that is what a lock is.
    with pytest.raises(CredentialError) as exc:
        await service.issue_token(client_id=cid, client_secret=created.secret, ip="")
    assert exc.value.code == "client_locked"
    assert exc.value.status_code == 423
    assert exc.value.retry_after == 900


async def test_the_lock_fails_closed_when_redis_is_down(pool) -> None:
    """The one place in this program where availability yields."""

    class DeadRedis:
        async def exists(self, *_a, **_k):
            raise ConnectionError("redis is down")

    lock = RedisClientLock(DeadRedis(), threshold=10, window_seconds=600, lock_seconds=900)
    with pytest.raises(LockUnavailableError):
        await lock.is_locked("anything")
    del pool


async def test_a_grant_refuses_with_503_when_the_lock_cannot_be_checked(
    service, pool, redis
) -> None:
    from pathlib import Path

    from ratelimit import FixedWindowLimiter

    class DeadRedis:
        async def exists(self, *_a, **_k):
            raise ConnectionError("down")

        async def incr(self, *_a, **_k):
            raise ConnectionError("down")

    keys = KeySet.from_json(
        (
            Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"
        ).read_text()
    )
    degraded = CredentialService(
        repo=CredentialRepository(pool),
        tokens=TokenService(
            keys=keys, issuer="http://i", audience="mdx-api", access_ttl_seconds=900
        ),
        limiter=FixedWindowLimiter(redis, prefix="mdx:auth:rl"),
        lock=RedisClientLock(DeadRedis(), threshold=10, window_seconds=600, lock_seconds=900),
        denylist=None,
        platform_tenant_id=PLATFORM,
        revoked_ttl_seconds=1200,
    )
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    with pytest.raises(CredentialError) as exc:
        await degraded.issue_token(
            client_id=str(created.credential.id), client_secret=created.secret, ip=""
        )
    assert exc.value.status_code == 503
    assert exc.value.code == "try_again"
    assert exc.value.retry_after == 5


# ── rotation ─────────────────────────────────────────────────────────────


async def test_rotation_leaves_both_secrets_working_then_expires_the_old(service, su) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    cid = created.credential.id
    new_secret, old_expires_at = await service.rotate(cid)

    # Both work — that is what lets a room be re-keyed without a visit.
    assert await service.issue_token(client_id=str(cid), client_secret=created.secret, ip="")
    assert await service.issue_token(client_id=str(cid), client_secret=new_secret, ip="")
    assert len(await service.secrets_of(cid)) == 2
    assert old_expires_at is not None

    # Move the old secret's expiry into the past; only the new one remains.
    await su.execute(
        "UPDATE service_credential_secrets SET expires_at = now() - interval '1 minute'"
        " WHERE credential_id = $1 AND secret_prefix = $2",
        cid,
        cred.prefix_of(created.secret),
    )
    with pytest.raises(CredentialError):
        await service.issue_token(client_id=str(cid), client_secret=created.secret, ip="")
    assert await service.issue_token(client_id=str(cid), client_secret=new_secret, ip="")
    assert len(await service.secrets_of(cid)) == 1


async def test_a_third_live_secret_is_refused(service) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    await service.rotate(created.credential.id)
    with pytest.raises(CredentialError) as exc:
        await service.rotate(created.credential.id)
    assert exc.value.code == "rotation_in_progress"
    assert exc.value.status_code == 409


async def test_an_over_long_overlap_is_refused(service) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    with pytest.raises(CredentialError) as exc:
        await service.rotate(created.credential.id, old_ttl_seconds=999_999_999)
    assert exc.value.code == "invalid_request"


async def test_revoking_kills_every_live_secret(service, su) -> None:
    created = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None
    )
    new_secret, _ = await service.rotate(created.credential.id)
    await service.revoke(created.credential.id)
    for secret in (created.secret, new_secret):
        with pytest.raises(CredentialError):
            await service.issue_token(
                client_id=str(created.credential.id), client_secret=secret, ip=""
            )
    assert (
        await su.fetchval(
            "SELECT count(*) FROM service_credential_secrets"
            " WHERE credential_id = $1 AND revoked_at IS NULL",
            created.credential.id,
        )
        == 0
    )


# ── isolation ────────────────────────────────────────────────────────────


async def test_app_role_cannot_read_a_secret_hash(service) -> None:
    """`app_role` is what every product service in the fleet connects as."""
    await service.create(kind="device", tenant_id=TENANT_A, name=_name("room"), created_by=None)
    conn = await asyncpg.connect(APP_DSN)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM service_credential_secrets LIMIT 1")
    finally:
        await conn.close()


async def test_one_workspaces_devices_are_invisible_from_another(service) -> None:
    a = await service.create(
        kind="device", tenant_id=TENANT_A, name=_name("a-room"), created_by=None
    )
    b = await service.create(
        kind="device", tenant_id=TENANT_B, name=_name("b-room"), created_by=None
    )
    conn = await asyncpg.connect(APP_DSN)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(TENANT_A))
        visible = {r["id"] for r in await conn.fetch("SELECT id FROM service_credentials")}
        assert a.credential.id in visible
        assert b.credential.id not in visible
    finally:
        await conn.close()


async def test_service_rows_are_invisible_to_app_role_entirely(service) -> None:
    """Their tenant_id is NULL, so the RLS predicate is never true — a
    machine that serves the platform is not a workspace's business."""
    created = await service.create(
        kind="service", tenant_id=None, name=_name("svc"), created_by=None
    )
    conn = await asyncpg.connect(APP_DSN)
    try:
        for tenant in (TENANT_A, TENANT_B, PLATFORM):
            await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant))
            rows = await conn.fetch(
                "SELECT id FROM service_credentials WHERE id = $1", created.credential.id
            )
            assert rows == []
    finally:
        await conn.close()


async def test_the_database_refuses_a_kind_tenant_mismatch(pool) -> None:
    """The CHECK is the real guard; the API's 400 is only a nicer message."""
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO service_credentials (kind, tenant_id, name, roles)"
                " VALUES ('service', $1, $2, ARRAY['service'])",
                TENANT_A,
                _name("bad"),
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO service_credentials (kind, tenant_id, name, roles)"
                " VALUES ('device', $1, $2, ARRAY['tenant_admin'])",
                TENANT_A,
                _name("bad"),
            )
