from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from telemetry import retention


class _Conn:
    def __init__(self, log: list[str], deletes: list[int]) -> None:
        self.log, self.deletes = log, deletes

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        # app_role sees no `tenants` rows outside a tenant context: the ids-only function.
        assert "telemetry_tenants(" in sql
        return [{"tenant_id": uuid4()}, {"tenant_id": uuid4()}]

    async def execute(self, sql: str, *args: Any) -> str:
        self.log.append(sql.split()[0])
        if sql.lstrip().startswith("DELETE"):
            return f"DELETE {self.deletes.pop(0) if self.deletes else 0}"
        if sql.lstrip().startswith("UPDATE"):
            return "UPDATE 1"
        return "SELECT 1"


class _Pool:
    def __init__(self, deletes: list[int]) -> None:
        self.log: list[str] = []
        self.deletes = deletes

    @asynccontextmanager
    async def _cm(self) -> Any:
        yield _Conn(self.log, self.deletes)

    def acquire(self) -> Any:
        return self._cm()


async def test_purge_deletes_in_batches_and_closes_stale_runs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pool = _Pool(deletes=[2, 2, 1, 0])

    @asynccontextmanager
    async def fake_tenant_connection(p: Any, tid: Any) -> Any:
        yield _Conn(p.log, p.deletes)

    monkeypatch.setattr(retention, "tenant_connection", fake_tenant_connection)
    result = await retention.purge(pool, batch=2)
    # tenant 1: 2 (full batch) + 2 (full) + 1 (short); tenant 2: 0.
    assert (result.tenants, result.deleted_runs, result.closed_stale_runs) == (2, 5, 2)
