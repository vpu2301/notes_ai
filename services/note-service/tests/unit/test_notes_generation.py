"""``POST /v1/notes/{id}/generation`` — the route behind *Generate Summary*.

Same rig shape as ``test_notes_meeting``: real app, real handler, the
repository and the engine patched at the module seam. The engine's four
refusals each have a status and a code the clients switch on; this pins
them.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteStatus

AUTHOR = UUID("00000000-0000-0000-0000-00000000000a")
TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
NOTE_ID = UUID("00000000-0000-0000-0000-00000000000b")
JOB_ID = UUID("00000000-0000-0000-0000-00000000000c")


def _claims() -> Claims:
    return Claims(
        sub=AUTHOR,
        tid=TENANT,
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note_row(**over: object) -> SimpleNamespace:
    row = SimpleNamespace(
        id=NOTE_ID,
        tenant_id=TENANT,
        code="NOTE-2026-00042",
        status=NoteStatus.DRAFT,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        shared_with_ids=[],
        visibility="private",
        title="Untitled meeting",
        source_asr_job_id=JOB_ID,
        deleted_at=None,
    )
    for key, value in over.items():
        setattr(row, key, value)
    return row


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_generation as rg

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            job_queue=object(),
            transcripts_store=object(),
            redis=None,
        )
    )
    store = SimpleNamespace(note=_note_row(), start_calls=[], start_raises=None)

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield SimpleNamespace()

    monkeypatch.setattr(rg, "tenant_connection", _tenant_conn)

    async def _fetch_note(conn, *, note_id, include_deleted=False):  # noqa: ANN001
        return store.note

    monkeypatch.setattr(rg.repo, "fetch_note", _fetch_note)

    async def _fetch_transcript(job_id, *, auth_header):  # noqa: ANN001
        return {"language": "en", "result_rev": 3, "segments": [{"text": "We ship on Friday."}]}

    monkeypatch.setattr(rg, "_fetch_transcript", _fetch_transcript)

    async def _start(conn, **kwargs):  # noqa: ANN001, ANN003
        store.start_calls.append(kwargs)
        if store.start_raises is not None:
            raise store.start_raises
        return uuid4(), "queued"

    monkeypatch.setattr(rg.generation_service, "start", _start)

    async def _emit_budget_reached(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(rg, "emit_budget_reached", _emit_budget_reached)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    return SimpleNamespace(client=TestClient(app), module=rg, store=store, audit_calls=audit_calls)


def test_generate_summary_queues_a_regenerate_for_the_note(rig: SimpleNamespace) -> None:
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    (call,) = rig.store.start_calls
    assert call["note_id"] == NOTE_ID
    assert call["reason"] == "regenerate"
    assert call["transcript_rev"] == 3
    # Somebody pressing the button is rate-limited; the automatic run is not.
    assert call["enforce_limit"] is True
    (event,) = rig.audit_calls
    assert event["payload"] == {"reason": "regenerate"}


def test_a_note_typed_by_hand_has_nothing_to_summarise(rig: SimpleNamespace) -> None:
    rig.store.note = _note_row(source_asr_job_id=None)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == 409
    assert resp.json()["code"] == "no_transcript"
    assert rig.store.start_calls == []


def test_a_cancelled_note_is_not_written(rig: SimpleNamespace) -> None:
    rig.store.note = _note_row(status=NoteStatus.CANCELLED)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == 409
    assert resp.json()["code"] == "note_cancelled"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        ("GenerationBusyError", 409, "generation_in_progress"),
        ("GenerationDisabledError", 409, "generation_disabled"),
        ("GenerationRateLimitedError", 429, "too_many_generations"),
    ],
)
def test_each_engine_refusal_has_its_code(
    rig: SimpleNamespace, error: str, status: int, code: str
) -> None:
    rig.store.start_raises = getattr(rig.module.generation_service, error)()
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == status
    assert resp.json()["code"] == code


def test_a_spent_budget_says_how_much(rig: SimpleNamespace) -> None:
    rig.store.start_raises = rig.module.generation_service.BudgetExceededError(2_100, 2_000)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert (body["spent_cents"], body["budget_cents"]) == (2_100, 2_000)
