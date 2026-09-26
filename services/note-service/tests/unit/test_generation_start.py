"""`generation_service.start`: the snapshot, the row and the job must all
name the SAME generation id.

The snapshot is sealed with the generation id as authenticated data and
stored under a key that carries it. Until this was pinned, the row was
inserted without that id, the database picked another, and the worker
tried to unwrap the snapshot with the row's id — every real generation
failed with "DEK unwrap failed" and the note stayed a bare transcript.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from note_service.domain import generation_repository as gen_repo
from note_service.domain import generation_service as gen


class _Store:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.puts.append({"key": key, "tenant_id": tenant_id, "aad": aad})


class _Queue:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def enqueue(self, tenant_id: UUID, kind: str, payload: dict[str, Any], **_: Any) -> None:
        self.payloads.append(payload)


async def test_snapshot_aad_row_id_and_job_payload_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    async def _create(conn: Any, **kw: Any) -> UUID:
        created.append(kw)
        # What the database does with an explicit id: it keeps it.
        assert kw["generation_id"] is not None
        return kw["generation_id"]

    async def _allowed(conn: Any, *, tenant_id: UUID) -> None:
        return None

    monkeypatch.setattr(gen_repo, "create", _create)
    monkeypatch.setattr(gen, "check_allowed", _allowed)

    store, queue = _Store(), _Queue()
    tenant, note = uuid4(), uuid4()
    generation_id, status = await gen.start(
        object(),
        queue=queue,
        store=store,
        tenant_id=tenant,
        note_id=note,
        requested_by=uuid4(),
        transcript={"language": "de", "segments": []},
    )

    assert status == gen_repo.QUEUED
    (put,) = store.puts
    assert put["aad"] == generation_id.bytes
    assert put["key"] == gen.snapshot_key(tenant, note, generation_id)
    assert created[0]["generation_id"] == generation_id
    assert created[0]["snapshot_key"] == put["key"]
    assert queue.payloads == [{"generation_id": str(generation_id), "note_id": str(note)}]
