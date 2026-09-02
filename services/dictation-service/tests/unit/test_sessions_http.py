"""GET /dictate/sessions list + detail echo the ambient-capture fields.

Pure handler tests: ``get_state``/``tenant_connection`` are monkeypatched
on the router module and the repository readers return canned rows, so
no DB or FastAPI app is needed. The rows are plain dicts — like
``asyncpg.Record`` they support both ``row["k"]`` and ``row.get("k")``.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from auth import Claims
from dictation_service.domain import repository as repository_mod
from dictation_service.routers import sessions as sessions_mod

TENANT_ID = uuid4()
USER_ID = uuid4()
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _claims() -> Claims:
    now = int(time.time())
    return Claims(
        sub=USER_ID,
        tid=TENANT_ID,
        roles=["member"],
        sid="sess-1",
        iss="https://kc.example/realms/notes",
        aud="mdx-api",
        exp=now + 3600,
        iat=now,
    )


def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _fake_tenant_connection(_pool: Any, _tenant_id: UUID) -> Any:
        yield SimpleNamespace()

    monkeypatch.setattr(sessions_mod, "get_state", lambda: SimpleNamespace(app_pool=None))
    monkeypatch.setattr(sessions_mod, "tenant_connection", _fake_tenant_connection)


def _summary_row(session_id: UUID, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": session_id,
        "status": "active",
        "language": "en",
        "target_kind": "generic",
        "capture_source": "browser",
        "device_name": None,
        "started_at": NOW,
        "last_active_at": NOW,
    }
    row.update(overrides)
    return row


async def test_list_echoes_capture_source_and_device_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)
    browser_id, room_id = uuid4(), uuid4()
    rows = [
        _summary_row(browser_id),
        _summary_row(room_id, capture_source="room_device", device_name="Berlin 4F"),
    ]

    async def _list_active(_conn: Any, *, user_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(repository_mod, "list_active_sessions_for_user", _list_active)

    out = await sessions_mod.list_sessions(claims=_claims(), limit=50, status_filter=None)

    by_id = {s.id: s for s in out}
    assert by_id[browser_id].capture_source == "browser"
    assert by_id[browser_id].device_name is None
    assert by_id[room_id].capture_source == "room_device"
    assert by_id[room_id].device_name == "Berlin 4F"


async def test_detail_echoes_capture_source_and_device_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)
    session_id = uuid4()
    row = {
        "id": session_id,
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "status": "finalized",
        "language": "en",
        "target_kind": "note",
        "capture_source": "room_device",
        "device_name": "Berlin 4F",
        "transcript_jsonb": "[]",
        "total_audio_ms": 1200,
        "avg_partial_latency_ms": None,
        "avg_final_latency_ms": None,
        "network_drop_count": 0,
        "started_at": NOW,
        "last_active_at": NOW,
        "finalized_at": NOW,
    }

    async def _get_session(_conn: Any, *, session_id: UUID) -> dict[str, Any]:
        return row

    monkeypatch.setattr(repository_mod, "get_session", _get_session)

    detail = await sessions_mod.get_session(session_id, claims=_claims())

    assert detail.capture_source == "room_device"
    assert detail.device_name == "Berlin 4F"
