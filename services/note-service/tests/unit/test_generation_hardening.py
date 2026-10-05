"""Sprint 37 — what the generation path does when nobody is watching.

Shadow runs, snapshot retention and the removal of the synthesis stub:
three things whose failure mode is silent. A shadow run that stored its
output would be a second copy of every sampled meeting; a snapshot that
outlived its generation would be a second copy of every meeting, full
stop; and a retired route that still answers is an attack surface
nobody owns.
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


# ── Shadow runs ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_no_shadow_backend_means_no_second_model_call(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []
    monkeypatch.setattr(generate_note.pipeline, "run", lambda *a, **k: calls.append("run"))

    await generate_note._shadow_run(
        _deps(), TENANT, uuid4(), {}, _Document(3), role_by_key={}, language="en"
    )
    assert calls == []


@pytest.mark.anyio
async def test_the_sample_is_a_sample_of_meetings_not_of_attempts(monkeypatch) -> None:  # noqa: ANN001
    """Deterministic on the generation id: re-running the same generation
    makes the same choice, so 5 % means 5 % of meetings — not 5 % of the
    attempts a retried meeting happens to make."""
    ran: list[UUID] = []

    async def _provider(_workspace):  # noqa: ANN001, ANN202
        return SimpleNamespace(backend_name="candidate")

    deps = _deps(shadow_provider_for=_provider, shadow_percent=5)

    async def _record(gid: UUID):  # noqa: ANN202
        async def _inner(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
            ran.append(gid)
            return _Document(2)

        return _inner

    ids = [uuid4() for _ in range(300)]
    for gid in ids:
        before = len(ran)
        monkeypatch.setattr(generate_note.pipeline, "run", await _record(gid))
        await generate_note._shadow_run(
            deps, TENANT, gid, {}, _Document(3), role_by_key={}, language="en"
        )
        assert (len(ran) > before) == (gid.int % 100 < 5)

    # Same generation twice, same decision.
    sampled = next((g for g in ids if g.int % 100 < 5), UUID(int=0))
    ran.clear()
    monkeypatch.setattr(generate_note.pipeline, "run", await _record(sampled))
    for _ in range(2):
        await generate_note._shadow_run(
            deps, TENANT, sampled, {}, _Document(3), role_by_key={}, language="en"
        )
    assert len(ran) == 2


@pytest.mark.anyio
async def test_a_workspace_that_has_not_acknowledged_the_candidate_is_not_shadowed(
    monkeypatch,  # noqa: ANN001
) -> None:
    """The provider factory says None, and the pipeline is never run: a
    shadow run processes a real meeting, so it only ever happens on a
    processor the workspace already agreed to."""
    calls: list[str] = []
    monkeypatch.setattr(generate_note.pipeline, "run", lambda *a, **k: calls.append("run"))

    async def _no_provider(_workspace):  # noqa: ANN001, ANN202
        return None

    gid = UUID(int=0)  # 0 % 100 == 0 → inside any sample
    await generate_note._shadow_run(
        _deps(shadow_provider_for=_no_provider, shadow_percent=100),
        TENANT,
        gid,
        {},
        _Document(3),
        role_by_key={},
        language="en",
    )
    assert calls == []


@pytest.mark.anyio
async def test_a_failing_shadow_run_never_touches_the_real_note(monkeypatch) -> None:  # noqa: ANN001
    async def _boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("candidate backend is down")

    monkeypatch.setattr(generate_note.pipeline, "run", _boom)

    async def _provider(_workspace):  # noqa: ANN001, ANN202
        return SimpleNamespace(backend_name="candidate")

    # No exception escapes: the note is already written by this point.
    await generate_note._shadow_run(
        _deps(shadow_provider_for=_provider, shadow_percent=100),
        TENANT,
        UUID(int=0),
        {},
        _Document(3),
        role_by_key={},
        language="en",
    )


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
