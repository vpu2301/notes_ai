"""`generation_service.start`: the snapshot, the row and the job must all name
the SAME generation id (the snapshot is sealed with it as AAD), or the worker
can never unwrap the snapshot.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from note_service.domain import generation_repository as gen_repo
from note_service.domain import generation_service as gen
from note_service.domain import prompt_profile_repository as profile_repo
from note_service.domain import prompt_profiles as profiles


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

    async def _allowed(conn: Any, *, tenant_id: UUID, **_kw) -> None:
        return None

    async def _bundled(conn: Any, *, tenant_id: UUID) -> Any:
        return profiles.BUNDLED, None

    monkeypatch.setattr(gen_repo, "create", _create)
    monkeypatch.setattr(gen, "check_allowed", _allowed)
    monkeypatch.setattr(profile_repo, "active_config", _bundled)

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

    # S3: what the job runs with is pinned on the row now, not read when it runs.
    pinned = created[0]["config_snapshot"]
    assert pinned["profile_version_id"] is None
    assert pinned["prompt_version"] == created[0]["prompt_version"]
    assert set(pinned["prompt_hashes"]) == set(profiles.STAGES)
    assert all(m == {"routed": True} for m in pinned["models"].values())


async def test_an_active_profile_this_deployment_cannot_run_fails_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    marked: list[dict[str, Any]] = []

    async def _create(conn: Any, **kw: Any) -> UUID:
        return kw["generation_id"]

    async def _mark(conn: Any, **kw: Any) -> None:
        marked.append(kw)

    async def _allowed(conn: Any, *, tenant_id: UUID, **_kw: Any) -> None:
        return None

    old = profile_repo.Version(
        id=uuid4(),
        profile_id=uuid4(),
        version_number=1,
        config=profiles.ProfileConfig(),
        contract_version="2020-01-01.1",
        schema_version="x",
        algorithm_version="old",
        content_hash="h",
        created_by=uuid4(),
        created_at=datetime.now(UTC),
    )

    async def _active(conn: Any, *, tenant_id: UUID) -> Any:
        return old.config, old

    monkeypatch.setattr(gen_repo, "create", _create)
    monkeypatch.setattr(gen_repo, "mark", _mark)
    monkeypatch.setattr(gen, "check_allowed", _allowed)
    monkeypatch.setattr(profile_repo, "active_config", _active)
    queue = _Queue()
    _id, status = await gen.start(
        object(),
        queue=queue,
        store=_Store(),
        tenant_id=uuid4(),
        note_id=uuid4(),
        requested_by=uuid4(),
        transcript={"language": "de", "segments": []},
    )
    assert status == gen_repo.FAILED and queue.payloads == []
    assert marked[0]["error_kind"] == gen.PROFILE_INCOMPATIBLE
