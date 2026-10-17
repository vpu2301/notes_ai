"""Presence (W3 B-6) with a fake Redis and a fake clock: the caller is never
listed, a heartbeat older than 45 s drops out, and Redis down means nobody.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import notes_repository as repo

TENANT = UUID("22222222-2222-2222-2222-222222222222")
AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
ANNA = UUID("33333333-3333-3333-3333-333333333331")
BORIS = UUID("33333333-3333-3333-3333-333333333332")
STRANGER = UUID("33333333-3333-3333-3333-333333333339")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
NAMES = {AUTHOR: "Author", ANNA: "Anna", BORIS: "Boris"}


def _claims(sub: UUID) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


class _FakeRedis:
    """The sorted-set subset presence uses; scores are seconds."""

    def __init__(self) -> None:
        self.z: dict[str, dict[bytes, float]] = {}
        self.ttl: dict[str, int] = {}

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.z.setdefault(key, {}).update({k.encode(): v for k, v in mapping.items()})
        return 1

    async def zremrangebyscore(self, key: str, low: str, high: float) -> int:
        members = self.z.get(key, {})
        gone = [m for m, s in members.items() if s <= high]
        for m in gone:
            del members[m]
        return len(gone)

    async def zrangebyscore(self, key: str, low: float, high: str) -> list[bytes]:
        return [m for m, s in self.z.get(key, {}).items() if s >= low]

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttl[key] = seconds
        return True


class _DownRedis:
    async def zadd(self, *a, **k):  # noqa: ANN002, ANN003
        raise ConnectionError("down")

    zremrangebyscore = zrangebyscore = expire = zadd


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_presence as router_mod

    redis = _FakeRedis()
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(), redis=redis)
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(router_mod, "_now", lambda: clock["t"])

    note = repo.NoteRow(
        id=NOTE,
        tenant_id=TENANT,
        code="N-2026-0001",
        status=repo.NoteStatus.DRAFT,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        title="Kickoff",
        created_at=NOW,
        updated_at=NOW,
        finalized_at=None,
        cancelled_at=None,
        visibility="private",
        collaborators={ANNA: "view", BORIS: "comment"},
    )

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return note if note_id == NOTE else None

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        return [SimpleNamespace(sub=s, email="x@acme.com", display_name=NAMES[s]) for s in subs]

    monkeypatch.setattr(repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(repo, "fetch_members", _fetch_members)

    app = create_app()
    who = {"claims": _claims(AUTHOR)}
    app.dependency_overrides[deps.current_user] = lambda: who["claims"]
    c = TestClient(app)
    c.who = who  # type: ignore[attr-defined]
    c.clock = clock  # type: ignore[attr-defined]
    c.redis = redis  # type: ignore[attr-defined]
    return c


def _as(client: TestClient, sub: UUID) -> TestClient:
    client.who["claims"] = _claims(sub)  # type: ignore[attr-defined]
    return client


def _viewers(client: TestClient, sub: UUID) -> list[str]:
    r = _as(client, sub).get(f"/v1/notes/{NOTE}/presence")
    assert r.status_code == 200, r.text
    return [v["display_name"] for v in r.json()["viewers"]]


def test_heartbeat_lists_others_but_never_the_caller(client: TestClient) -> None:
    assert _as(client, ANNA).post(f"/v1/notes/{NOTE}/presence").status_code == 204
    assert _as(client, BORIS).post(f"/v1/notes/{NOTE}/presence").status_code == 204
    assert client.redis.ttl[f"note:presence:{TENANT}:{NOTE}"] == 45  # type: ignore[attr-defined]

    assert sorted(_viewers(client, AUTHOR)) == ["Anna", "Boris"]
    assert _viewers(client, ANNA) == ["Boris"]


def test_a_heartbeat_expires_after_45_seconds(client: TestClient) -> None:
    _as(client, ANNA).post(f"/v1/notes/{NOTE}/presence")
    client.clock["t"] += 30  # type: ignore[attr-defined]
    _as(client, BORIS).post(f"/v1/notes/{NOTE}/presence")
    assert sorted(_viewers(client, AUTHOR)) == ["Anna", "Boris"]

    client.clock["t"] += 20  # Anna's beat is 50 s old, Boris's 20 s.
    assert _viewers(client, AUTHOR) == ["Boris"]

    client.clock["t"] += 30
    assert _viewers(client, AUTHOR) == []


def test_someone_who_cannot_see_the_note_gets_404(client: TestClient) -> None:
    assert _as(client, STRANGER).post(f"/v1/notes/{NOTE}/presence").status_code == 404
    assert _as(client, STRANGER).get(f"/v1/notes/{NOTE}/presence").status_code == 404
    assert client.redis.z == {}  # type: ignore[attr-defined]


def test_redis_down_fails_open(client: TestClient) -> None:
    from note_service import deps

    deps.get_state().redis = _DownRedis()  # type: ignore[attr-defined]
    assert _as(client, ANNA).post(f"/v1/notes/{NOTE}/presence").status_code == 204
    assert _viewers(client, AUTHOR) == []
