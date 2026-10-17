"""The socket registry is keyed by (user, workspace): a person signed into two
workspaces never receives one workspace's frames on the other's socket (W1).
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from notification_service.ws import handler
from notification_service.ws.registry import SocketRegistry

USER = uuid4()
TENANT_A = uuid4()
TENANT_B = uuid4()


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


async def _two_sockets() -> tuple[SocketRegistry, FakeSocket, FakeSocket]:
    registry = SocketRegistry()
    in_a, in_b = FakeSocket(), FakeSocket()
    await registry.add(USER, TENANT_A, in_a)
    await registry.add(USER, TENANT_B, in_b)
    return registry, in_a, in_b


@pytest.mark.asyncio
async def test_a_frame_reaches_only_its_workspace_socket() -> None:
    registry, in_a, in_b = await _two_sockets()

    assert await registry.send_to_user(USER, TENANT_A, "a-frame") == 1

    assert in_a.sent == ["a-frame"]
    assert in_b.sent == []


@pytest.mark.asyncio
async def test_counts_are_people_and_sockets() -> None:
    registry, _, _ = await _two_sockets()

    assert registry.connected_user_count() == 1
    assert registry.connected_socket_count() == 2


@pytest.mark.asyncio
async def test_removing_one_workspace_socket_keeps_the_other() -> None:
    registry, in_a, in_b = await _two_sockets()

    await registry.remove(USER, TENANT_A, in_a)

    assert await registry.sockets_for(USER, TENANT_A) == []
    assert await registry.sockets_for(USER, TENANT_B) == [in_b]


def _state(registry: SocketRegistry, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Unread counts are per workspace (RLS): A has 3 unread, B has 7."""
    unread = {TENANT_A: 3, TENANT_B: 7}

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield SimpleNamespace(tenant_id=tenant_id)

    async def _unread_count(conn: Any, *, user_id: UUID) -> int:
        return unread[conn.tenant_id]

    monkeypatch.setattr(handler, "tenant_connection", _conn)
    monkeypatch.setattr(handler.repo, "unread_count", _unread_count)
    return SimpleNamespace(socket_registry=registry, app_pool=object())


@pytest.mark.asyncio
async def test_fanout_for_workspace_a_never_reaches_workspace_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, in_a, in_b = await _two_sockets()
    handle = handler.make_fanout_handler(_state(registry, monkeypatch))

    await handle(
        {"kind": "unread_count", "tenant_id": str(TENANT_A), "recipient_user_id": str(USER)}
    )

    assert [json.loads(f)["unread_count"] for f in in_a.sent] == [3]
    assert in_b.sent == []


@pytest.mark.asyncio
async def test_fanout_frame_without_tenant_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    registry, in_a, in_b = await _two_sockets()
    handle = handler.make_fanout_handler(_state(registry, monkeypatch))

    await handle({"kind": "unread_count", "recipient_user_id": str(USER)})

    assert in_a.sent == in_b.sent == []
