"""`POST /auth/leads` — the fake door behind the shared page's CTA.

What matters: the row is written with the code, the address reaches no
audit payload, a repeat is not a second lead, and a missing consent or a
bad address is refused before anything is stored.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observability import register_exception_handlers


class FakeConn:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows

    async def execute(self, sql: str, ref_code: str, email: str) -> str:
        if (email, ref_code) in self.rows:
            return "INSERT 0 0"
        self.rows.append((email, ref_code))
        return "INSERT 0 1"


class FakePool:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def acquire(self) -> Any:
        rows = self.rows

        class _Acquire:
            async def __aenter__(self) -> FakeConn:
                return FakeConn(rows)

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Acquire()


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incrby(self, key: str, n: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + n
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        pass


@pytest.fixture
def env() -> tuple[TestClient, FakePool, list[dict[str, Any]]]:
    from auth_service import deps
    from auth_service.routers import leads

    pool, audit = FakePool(), []

    async def _write_event(**kw: Any) -> None:
        audit.append(kw)

    class _Audit:
        write_event = staticmethod(_write_event)

    class _State:
        tenant_writer_pool = pool
        audit_writer = _Audit()
        _redis = FakeRedis()

    deps.install_state(_State())  # type: ignore[arg-type]
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(leads.router)
    return TestClient(app), pool, audit


def test_lead_is_stored_with_its_ref_and_kept_out_of_audit(env) -> None:  # noqa: ANN001
    client, pool, audit = env
    r = client.post(
        "/auth/leads", json={"email": "Tom@Client.com", "ref": "abcdefghijkl", "consent": True}
    )
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    assert pool.rows == [("tom@client.com", "abcdefghijkl")]
    assert [a["kind"] for a in audit] == ["lead.captured"]
    assert audit[0]["payload"] == {"ref_present": True}
    assert "client.com" not in repr(audit)


def test_repeat_submit_is_one_lead(env) -> None:  # noqa: ANN001
    client, pool, audit = env
    body = {"email": "tom@client.com", "ref": "abcdefghijkl", "consent": True}
    assert client.post("/auth/leads", json=body).status_code == 202
    assert client.post("/auth/leads", json=body).status_code == 202
    assert len(pool.rows) == 1
    assert len(audit) == 1


def test_public_link_cta_has_no_ref_and_still_counts(env) -> None:  # noqa: ANN001
    client, pool, audit = env
    assert client.post("/auth/leads", json={"email": "a@b.co", "consent": True}).status_code == 202
    assert pool.rows == [("a@b.co", "")]
    assert audit[0]["payload"] == {"ref_present": False}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-address", "ref": "abcdefghijkl", "consent": True},
        {"email": "tom@client.com", "ref": "abcdefghijkl", "consent": False},
        {"email": "tom@client.com", "ref": "abcdefghijkl"},
        {"email": "tom@client.com", "ref": "NOT A CODE", "consent": True},
    ],
)
def test_bad_input_is_refused_before_storage(env, body: dict[str, Any]) -> None:  # noqa: ANN001
    client, pool, audit = env
    assert client.post("/auth/leads", json=body).status_code == 422
    assert pool.rows == []
    assert audit == []


def test_twenty_first_submit_from_one_ip_is_429(env) -> None:  # noqa: ANN001
    client, _pool, _audit = env
    for i in range(20):
        body = {"email": f"p{i}@client.com", "consent": True}
        assert client.post("/auth/leads", json=body).status_code == 202
    r = client.post("/auth/leads", json={"email": "p99@client.com", "consent": True})
    assert r.status_code == 429
    assert "retry-after" in r.headers
