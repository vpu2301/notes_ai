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


# ── GET: exclusions and coverage (Summary Engine v2, Q2) ────────────


def _generation_row(stats: dict) -> SimpleNamespace:
    from datetime import UTC, datetime

    return SimpleNamespace(
        id=uuid4(),
        note_id=NOTE_ID,
        status="complete",
        step=None,
        windows_total=3,
        windows_done=3,
        windows_failed=0,
        failed_ranges=[],
        prompt_version="2026-10-7",
        model_id="notes-chat",
        error_kind=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        finished_at=datetime(2026, 9, 22, tzinfo=UTC),
        stats=stats,
    )


def _serve_generation(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, row: object) -> None:
    async def _latest(conn, *, note_id):  # noqa: ANN001
        return row

    monkeypatch.setattr(rig.module.gen_repo, "latest_for_note", _latest)


def test_the_generation_says_what_was_left_out_and_how_facts_cover_the_recording(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    stats = {
        "section_hashes": {"gen:overview": "x"},
        "excluded_ranges": [[150_000, 153_000, "artifact"]],
        "facts_by_third": [7, 5, 6],
        "speech_ms": 418_000,
        "excluded_ms": 3_000,
        "recording_type": "podcast_broadcast",
        "recording_type_source": "classifier",
        "language": "de",
    }
    _serve_generation(rig, monkeypatch, _generation_row(stats))
    body = rig.client.get(f"/v1/notes/{NOTE_ID}/generation").json()
    assert body["excluded_ranges"] == [
        {"start_ms": 150_000, "end_ms": 153_000, "reason": "artifact"}
    ]
    assert body["coverage"] == {
        "facts_by_third": [7, 5, 6],
        "speech_ms": 418_000,
        "excluded_ms": 3_000,
    }
    # Q3: what the recording was taken to be, and who decided.
    assert (body["recording_type"], body["recording_type_source"], body["language"]) == (
        "podcast_broadcast",
        "classifier",
        "de",
    )


def test_a_generation_from_before_q2_has_no_exclusions_and_no_coverage(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_generation(rig, monkeypatch, _generation_row({"section_hashes": {}}))
    body = rig.client.get(f"/v1/notes/{NOTE_ID}/generation").json()
    assert body["excluded_ranges"] == []
    assert body["coverage"] is None
    assert body["recording_type"] is None and body["recording_type_source"] is None


def test_another_workspaces_generation_is_not_found(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under RLS the other workspace's note reads as absent: 404, and the
    generation row is never looked up."""
    rig.store.note = None
    looked_up: list[object] = []

    async def _latest(conn, *, note_id):  # noqa: ANN001
        looked_up.append(note_id)
        return _generation_row({"excluded_ranges": [[0, 1, "background"]]})

    monkeypatch.setattr(rig.module.gen_repo, "latest_for_note", _latest)
    resp = rig.client.get(f"/v1/notes/{NOTE_ID}/generation")
    assert resp.status_code == 404
    assert looked_up == []


# ── Q5: rows for every line; key dates as .ics ──────────────────────


def _row(**over: object) -> dict:
    base = {
        "item_key": "a1b2c3d4e5f60718",
        "kind": "date",
        "section_key": "key_dates",
        "text": "23.09.2026 00:00 — Der Warnstreik endet, wenn keine Einigung kommt",
        "owner_label": None,
        "due_text": None,
        "due_date": None,
        "explicit": False,
        "confidence": 0.7,
        "flags": [],
        "quote": "Der Warnstreik soll bis Mittwoch 0 Uhr dauern; danach, sagt er, sehen wir weiter",
        "start_ms": 300_000,
        "end_ms": 310_000,
        "speaker_label": "SPEAKER_2",
        "speaker_name": "Jonas Pfeffer",
        "placement": "written",
        "audience": "all",
        "cites": ["f1"],
        "certainty": "prediction",
        "attributed_to": "Jonas Pfeffer",
        "corrections": '[{"surface": "Jonas Pfefer", "canonical": "Jonas Pfeffer", "source": "candidate"}]',
        "mentions": '[{"text": "bis mittwoch 0 uhr", "date": "2026-09-23", "time": "00:00", "direction": "future"}]',
    }
    base.update(over)
    return base


def _serve_items(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> list:
    seen: list = []

    async def _items(conn, *, note_id, current_only=False):  # noqa: ANN001
        seen.append(current_only)
        return rows

    from note_service.routers import notes_dates

    monkeypatch.setattr(rig.module.gen_repo, "items_for_note", _items)

    async def _reviewed(conn, *, note_id):  # noqa: ANN001
        return set(getattr(rig, "reviewed_tags", set()))

    monkeypatch.setattr(rig.module.glossary_repo, "reviewed_name_tags", _reviewed)
    monkeypatch.setattr(notes_dates, "tenant_connection", rig.module.tenant_connection)
    monkeypatch.setattr(notes_dates.repo, "fetch_note", rig.module.repo.fetch_note)
    return seen


def test_a_line_row_carries_what_it_cites_and_its_labels(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _serve_items(rig, monkeypatch, [_row()])
    [item] = rig.client.get(f"/v1/notes/{NOTE_ID}/generated-items?generation=current").json()
    assert seen == [True]
    assert item["cites"] == ["f1"]
    assert (item["certainty"], item["attributed_to"]) == ("prediction", "Jonas Pfeffer")
    assert item["corrections"][0]["surface"] == "Jonas Pfefer"
    assert item["mentions"][0]["time"] == "00:00"
    rig.client.get(f"/v1/notes/{NOTE_ID}/generated-items")
    assert seen == [True, False]  # default: every generation, as before


def test_a_respelling_the_author_decided_is_not_offered_again(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service.domain.glossary_repository import name_review_tag

    _serve_items(rig, monkeypatch, [_row()])
    rig.reviewed_tags = {name_review_tag("Jonas Pfefer", "Jonas Pfeffer")}
    [item] = rig.client.get(f"/v1/notes/{NOTE_ID}/generated-items?generation=current").json()
    assert item["corrections"] == []


def test_a_key_date_downloads_as_a_calendar_file(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_items(rig, monkeypatch, [_row()])
    resp = rig.client.get(f"/v1/notes/{NOTE_ID}/dates/a1b2c3d4e5f60718.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    body = resp.text
    assert "DTSTART:20260923T000000" in body
    assert "UID:a1b2c3d4e5f60718@" in body
    # The quote's ";" and "," are escaped per RFC 5545.
    assert "Mittwoch 0 Uhr dauern\\; danach\\, sagt er" in body.replace("\r\n ", "")
    (event,) = [e for e in rig.audit_calls if e["kind"] == "note.date_exported"]
    assert event["payload"] == {"item_key": "a1b2c3d4e5f60718", "timed": True}


def test_an_unknown_date_or_another_workspaces_note_is_not_found(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_items(rig, monkeypatch, [_row(kind="key_point")])
    assert rig.client.get(f"/v1/notes/{NOTE_ID}/dates/a1b2c3d4e5f60718.ics").status_code == 404
    rig.store.note = None  # under RLS, another workspace's note reads as absent
    assert rig.client.get(f"/v1/notes/{NOTE_ID}/dates/a1b2c3d4e5f60718.ics").status_code == 404
