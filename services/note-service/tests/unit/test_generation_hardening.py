"""What the generation path does when nobody is watching: snapshots do not outlive
their generation and the retired synthesis route does not answer. (Shadow runs went
with the old writing path, Sprint R0.)
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from note_service.domain import generation_repository as gen_repo
from note_service.jobs import generate_note, snapshot_sweeper

TENANT = UUID("22222222-2222-2222-2222-222222222222")


class _Document:
    def __init__(self, facts: int) -> None:
        self.facts = list(range(facts))
        self.windows_failed = 0


def _deps(**over) -> generate_note.GenerationDeps:  # noqa: ANN003
    base = {"app_pool": object(), "transcripts_store": object(), "provider_for": None}
    base.update(over)
    return generate_note.GenerationDeps(**base)  # type: ignore[arg-type]


# ── Snapshot retention ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_the_sweep_deletes_the_object_and_the_pointer(monkeypatch) -> None:  # noqa: ANN001
    deleted: list[str] = []
    cleared: list[UUID] = []
    stale = [(uuid4(), "tenant/generation/a.json"), (uuid4(), "tenant/generation/b.json")]

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield None

    async def _stale(conn, *, older_than_hours, limit=500):  # noqa: ANN001
        assert older_than_hours == 24
        return stale

    async def _clear(conn, *, generation_id):  # noqa: ANN001
        cleared.append(generation_id)
        return dict(stale)[generation_id]

    monkeypatch.setattr(snapshot_sweeper, "tenant_connection", _conn)
    monkeypatch.setattr(gen_repo, "stale_snapshots", _stale)
    monkeypatch.setattr(gen_repo, "clear_snapshot", _clear)

    store = SimpleNamespace(delete=lambda *, key: deleted.append(key))

    async def _delete(*, key):  # noqa: ANN001, ANN202
        deleted.append(key)

    store.delete = _delete
    swept = await snapshot_sweeper.sweep_tenant(app_pool=object(), store=store, tenant_id=TENANT)
    assert swept == 2
    assert deleted == [k for _, k in stale]
    assert cleared == [g for g, _ in stale]


@pytest.mark.anyio
async def test_one_undeletable_object_does_not_stop_the_sweep(monkeypatch) -> None:  # noqa: ANN001
    stale = [(uuid4(), "bad"), (uuid4(), "good")]

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield None

    async def _stale(conn, **_k):  # noqa: ANN001
        return stale

    async def _clear(conn, *, generation_id):  # noqa: ANN001
        return dict(stale)[generation_id]

    async def _delete(*, key):  # noqa: ANN001
        if key == "bad":
            raise RuntimeError("object store said no")

    monkeypatch.setattr(snapshot_sweeper, "tenant_connection", _conn)
    monkeypatch.setattr(gen_repo, "stale_snapshots", _stale)
    monkeypatch.setattr(gen_repo, "clear_snapshot", _clear)

    swept = await snapshot_sweeper.sweep_tenant(
        app_pool=object(), store=SimpleNamespace(delete=_delete), tenant_id=TENANT
    )
    assert swept == 1


# ── The retired route ───────────────────────────────────────────────


def test_the_synthesis_stub_is_gone(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service.main import create_app

    paths = {r.path for r in create_app().routes}  # type: ignore[attr-defined]
    assert not [p for p in paths if "synthes" in p]
