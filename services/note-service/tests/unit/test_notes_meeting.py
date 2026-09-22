"""The meeting surface: the note exists from the first second (Sprint 34).

Real handlers, auth overridden, the DB and asr-service boundaries stubbed
— the ``test_notes_from_transcript`` rig, extended with the ``note_meetings``
sidecar.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteSection, NoteStatus
from note_service.domain.meetings_repository import MeetingRow
from note_service.domain.template_match import TemplateCandidate
from template_models import TemplateDefinition

AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
JOB_ID = UUID("99999999-9999-9999-9999-999999999999")
CAPTURE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
STARTED_AT = "2026-09-20T09:00:00Z"

SECTIONS = [
    ("user_notes", "My notes"),
    ("attendees", "Attendees"),
    ("agenda", "Agenda"),
    ("discussion", "Discussion"),
    ("action_items", "Action items"),
]


def _definition(code: str) -> TemplateDefinition:
    return TemplateDefinition.model_validate(
        {
            "code": code,
            "name": code,
            "language": "en",
            "category": "meetings",
            "sections": [
                {"id": sid, "name": name, "asr_prompt": name, "order": i}
                for i, (sid, name) in enumerate(SECTIONS)
            ],
        }
    )


def _candidate(code: str) -> TemplateCandidate:
    return TemplateCandidate(
        id=uuid4(),
        code=code,
        name=code,
        category="meetings",
        schema_version=1,
        definition=_definition(code),
        is_system=True,
    )


CATALOGUE = [_candidate("meeting_notes"), _candidate("sales_call")]


def _claims(sub: UUID = AUTHOR, tid: UUID = TENANT) -> Claims:
    return Claims(
        sub=sub,
        tid=tid,
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
        current_version_id=VERSION_ID,
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        shared_with_ids=[],
        visibility="workspace",
        title="Untitled meeting",
        source_asr_job_id=None,
        deleted_at=None,
    )
    for key, value in over.items():
        setattr(row, key, value)
    return row


def _meeting_row(**over: object) -> MeetingRow:
    fields = {
        "note_id": NOTE_ID,
        "tenant_id": TENANT,
        "created_by": AUTHOR,
        "state": "recording",
        "client_capture_id": CAPTURE_ID,
        "asr_job_id": None,
        "meeting_type": "auto",
        "started_at": datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
        "calendar_context": {},
    }
    fields.update(over)
    return MeetingRow(**fields)  # type: ignore[arg-type]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_meeting as rm

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            # The engine (Sprint 33) is patched per test; these are the
            # handles the router passes it.
            job_queue=object(),
            transcripts_store=object(),
            redis=None,
        )
    )

    store = SimpleNamespace(
        note=_note_row(),
        meeting=None,
        by_capture=None,
        line_times={},
        executed=[],
        versions=[],
        unique_violation_on_bind=False,
    )

    conn = SimpleNamespace()

    async def _fetchval(query, *args):  # noqa: ANN001, ANN002
        return CATALOGUE[0].id if "template_id" in query else None

    async def _fetchrow(query, *args):  # noqa: ANN001, ANN002
        if "source_asr_job_id = $1" in query:
            return {"id": NOTE_ID, "code": "NOTE-2026-00001"}
        return None

    async def _execute(query, *args):  # noqa: ANN001, ANN002
        if store.unique_violation_on_bind and "source_asr_job_id = $2" in query:
            raise asyncpg.UniqueViolationError("duplicate")
        store.executed.append((query, args))

    conn.fetchval = _fetchval
    conn.fetchrow = _fetchrow
    conn.execute = _execute

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield conn

    monkeypatch.setattr(rm, "tenant_connection", _tenant_conn)

    async def _load_candidates(conn, *, language):  # noqa: ANN001
        return CATALOGUE

    monkeypatch.setattr(rm.template_match, "load_candidates", _load_candidates)

    async def _next_code(conn, *, tenant_id):  # noqa: ANN001
        return "NOTE-2026-00042"

    monkeypatch.setattr(rm.code_sequence, "next_code", _next_code)

    create_calls: list[dict] = []

    async def _create_note(conn, **kwargs):  # noqa: ANN001, ANN003
        create_calls.append(kwargs)
        return NOTE_ID, VERSION_ID

    async def _fetch_note(conn, *, note_id, include_deleted=False):  # noqa: ANN001
        return store.note

    async def _lock_note(conn, *, note_id):  # noqa: ANN001
        return store.note

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return SimpleNamespace(content=store.versions[-1] if store.versions else _content())

    async def _append_version(conn, **kwargs):  # noqa: ANN001, ANN003
        store.versions.append(kwargs["new_content"])
        return uuid4(), kwargs["expected_version"] + 1

    monkeypatch.setattr(rm.repo, "create_note_with_v1", _create_note)
    monkeypatch.setattr(rm.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(rm.repo, "lock_note_for_update", _lock_note)
    monkeypatch.setattr(rm.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(rm.repo, "append_version", _append_version)

    meeting_creates: list[dict] = []

    async def _meeting_create(conn, **kwargs):  # noqa: ANN001, ANN003
        meeting_creates.append(kwargs)
        store.meeting = _meeting_row(
            client_capture_id=kwargs["client_capture_id"],
            meeting_type=kwargs["meeting_type"],
            calendar_context=kwargs["calendar_context"],
        )

    async def _meeting_fetch(conn, *, note_id):  # noqa: ANN001
        return store.meeting

    async def _find_by_capture(conn, *, client_capture_id):  # noqa: ANN001
        return store.by_capture

    async def _set_state(conn, *, note_id, state):  # noqa: ANN001
        store.meeting = _meeting_row(
            state=state,
            asr_job_id=store.meeting.asr_job_id if store.meeting else None,
        )

    async def _bind_job(conn, *, note_id, asr_job_id):  # noqa: ANN001
        store.meeting = _meeting_row(state="transcribing", asr_job_id=asr_job_id)

    async def _put_line_times(conn, *, tenant_id, note_id, lines):  # noqa: ANN001
        written = 0
        for key, offset in lines:
            if key not in store.line_times:  # first report wins
                store.line_times[key] = offset
                written += 1
        return written

    monkeypatch.setattr(rm.meetings, "create", _meeting_create)
    monkeypatch.setattr(rm.meetings, "fetch", _meeting_fetch)
    monkeypatch.setattr(rm.meetings, "find_by_capture", _find_by_capture)
    monkeypatch.setattr(rm.meetings, "set_state", _set_state)
    monkeypatch.setattr(rm.meetings, "bind_job", _bind_job)
    monkeypatch.setattr(rm.meetings, "put_line_times", _put_line_times)

    async def _fetch_transcript(job_id, *, auth_header):  # noqa: ANN001
        return {
            "language": "en",
            "segments": [{"text": "The budget is fourteen thousand."}],
        }

    monkeypatch.setattr(rm, "_fetch_transcript", _fetch_transcript)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    return SimpleNamespace(
        client=TestClient(app),
        module=rm,
        store=store,
        create_calls=create_calls,
        meeting_creates=meeting_creates,
        audit_calls=audit_calls,
        app=app,
        deps=deps,
        monkeypatch=monkeypatch,
    )


def _content(user_notes: str = "") -> NoteContent:
    return NoteContent(
        template_id=CATALOGUE[0].id,
        template_schema_version=1,
        title="Untitled meeting",
        sections=[
            NoteSection(section_key=key, text=user_notes if key == "user_notes" else "")
            for key, _ in SECTIONS
        ],
    )


def _start(rig: SimpleNamespace, **over: object) -> object:
    body = {"client_capture_id": str(CAPTURE_ID), "started_at": STARTED_AT}
    body.update(over)  # type: ignore[arg-type]
    return rig.client.post("/v1/notes/meeting", json=body)


# ── Creating the note at record start ───────────────────────────────


def test_pressing_record_opens_a_note(rig: SimpleNamespace) -> None:
    resp = _start(rig, title="Weekly sync")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "NOTE-2026-00042"
    assert body["state"] == "recording"

    (call,) = rig.create_calls
    # No job yet: source_asr_job_id is set LATER (ADR-0055).
    assert call.get("source_asr_job_id") is None
    content = call["content"]
    assert content.title == "Weekly sync"
    # The scratchpad is there and EMPTY — a placeholder would be words the
    # author did not write.
    assert content.sections[0].section_key == "user_notes"
    assert content.sections[0].text == ""


def test_a_typed_title_is_the_authors_and_a_placeholder_is_not(rig: SimpleNamespace) -> None:
    """0057: only the server's placeholder may be renamed by the engine."""
    assert _start(rig, title="Weekly sync").status_code == 201
    assert rig.create_calls[-1]["title_source"] == "user"

    rig.create_calls.clear()
    assert _start(rig, client_capture_id=str(uuid4())).status_code == 201
    (call,) = rig.create_calls
    assert call["title_source"] == "default"
    assert call["content"].title.startswith("meeting_notes — ")


def test_a_calendar_title_is_never_replaced(rig: SimpleNamespace) -> None:
    resp = _start(rig, calendar={"source": "google", "title": "Acme <> Us"})
    assert resp.status_code == 201, resp.text
    (call,) = rig.create_calls
    assert call["content"].title == "Acme <> Us"
    assert call["title_source"] == "user"


def test_the_same_capture_id_returns_the_same_note(rig: SimpleNamespace) -> None:
    rig.store.by_capture = _meeting_row()
    resp = _start(rig)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(NOTE_ID)
    assert rig.create_calls == []  # no second note


def test_the_meeting_type_picks_the_template_family(rig: SimpleNamespace) -> None:
    resp = _start(rig, meeting_type="sales")
    assert resp.status_code == 201
    assert resp.json()["template_id"] == str(CATALOGUE[1].id)


def test_an_unknown_family_falls_back_to_meeting_notes(rig: SimpleNamespace) -> None:
    # "team" wants project_update, which this catalogue does not have.
    resp = _start(rig, meeting_type="team")
    assert resp.json()["template_id"] == str(CATALOGUE[0].id)


def test_the_invites_people_and_agenda_are_already_in_the_note(
    rig: SimpleNamespace,
) -> None:
    resp = _start(
        rig,
        calendar={
            "source": "google",
            "title": "Q3 review",
            "ical_uid": "abc@google.com",
            "attendee_names": ["Anna Keller", "anna keller", "Tom Berg"],
            "description": "Agenda:\n- Pipeline\n- Pricing\n- Hiring",
        },
    )
    assert resp.status_code == 201
    content = rig.create_calls[0]["content"]
    by_key = {s.section_key: s.text for s in content.sections}
    assert by_key["attendees"] == "Anna Keller\nTom Berg"  # de-duplicated
    assert by_key["agenda"] == "- [ ] Pipeline\n- [ ] Pricing\n- [ ] Hiring"
    # The raw description is never stored.
    stored = rig.meeting_creates[0]["calendar_context"]
    assert "description" not in stored
    assert stored["agenda_lines"] == ["Pipeline", "Pricing", "Hiring"]


def test_no_list_in_the_description_means_no_agenda(rig: SimpleNamespace) -> None:
    _start(
        rig,
        calendar={"source": "google", "description": "See you at https://meet.google.com/x"},
    )
    by_key = {s.section_key: s.text for s in rig.create_calls[0]["content"].sections}
    assert by_key["agenda"] == ""


def test_starting_a_meeting_never_audits_content(rig: SimpleNamespace) -> None:
    _start(
        rig,
        title="Acquisition of Pied Piper",
        calendar={
            "source": "google",
            "title": "Acquisition of Pied Piper",
            "attendee_names": ["Anna Keller"],
            "description": "Agenda:\n- Valuation\n- Term sheet",
        },
    )
    (event,) = rig.audit_calls
    blob = repr(event["payload"])
    for secret in ("Pied Piper", "Anna Keller", "Valuation", "Term sheet"):
        assert secret not in blob
    assert event["payload"] == {
        "code": "NOTE-2026-00042",
        "meeting_type": "auto",
        "has_calendar": True,
        "template_id": str(CATALOGUE[0].id),
    }


# ── Line times ──────────────────────────────────────────────────────


def test_the_first_keystroke_of_a_line_wins(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row()
    for offset in (4_000, 90_000):
        resp = rig.client.put(
            f"/v1/notes/{NOTE_ID}/my-notes/timing",
            json={"lines": [{"line_key": "abc123", "offset_ms": offset}]},
        )
        assert resp.status_code == 204, resp.text
    assert rig.store.line_times == {"abc123": 4_000}


def test_line_times_are_capped(rig: SimpleNamespace) -> None:
    resp = rig.client.put(
        f"/v1/notes/{NOTE_ID}/my-notes/timing",
        json={"lines": [{"line_key": f"k{i}", "offset_ms": i} for i in range(501)]},
    )
    assert resp.status_code == 422


# ── Attaching the recording ─────────────────────────────────────────


def test_attaching_a_job_moves_the_capture_to_transcribing(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row()
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/job", json={"asr_job_id": str(JOB_ID)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "transcribing"
    assert resp.json()["asr_job_id"] == str(JOB_ID)
    # Same pair again: idempotent, not a conflict.
    again = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/job", json={"asr_job_id": str(JOB_ID)})
    assert again.status_code == 200


def test_a_job_another_note_owns_is_a_conflict(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row()
    rig.store.unique_violation_on_bind = True
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/job", json={"asr_job_id": str(JOB_ID)})
    assert resp.status_code == 409
    assert resp.json()["code"] == "already_assigned"


def test_a_note_that_already_has_a_recording_refuses_a_second(
    rig: SimpleNamespace,
) -> None:
    rig.store.meeting = _meeting_row(asr_job_id=uuid4())
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/job", json={"asr_job_id": str(JOB_ID)})
    assert resp.status_code == 409


def test_the_transcript_lands_in_prose_and_leaves_my_notes_untouched(
    rig: SimpleNamespace,
) -> None:
    typed = "- Ask about budget\n- Tom hesitated here"
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content(user_notes=typed))

    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ready"

    written = rig.store.versions[-1]
    by_key = {s.section_key: s.text for s in written.sections}
    # Byte-identical: the author's characters are never touched.
    assert by_key["user_notes"] == typed
    assert by_key["discussion"] == "The budget is fourteen thousand."


def test_the_transcript_is_appended_to_prose_the_author_already_typed(
    rig: SimpleNamespace,
) -> None:
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    content = _content()
    content.sections[3].text = "my own summary"
    rig.store.versions.append(content)

    rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    by_key = {s.section_key: s.text for s in rig.store.versions[-1].sections}
    assert by_key["discussion"] == "my own summary\n\nThe budget is fourteen thousand."


def test_transcript_before_the_job_is_complete_passes_the_409_through(
    rig: SimpleNamespace,
) -> None:
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)

    async def _not_ready(job_id, *, auth_header):  # noqa: ANN001
        raise HTTPException(409, detail={"code": "job_not_complete"})

    rig.monkeypatch.setattr(rig.module, "_fetch_transcript", _not_ready)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 409
    assert rig.store.meeting.state == "transcribing"  # unchanged


def test_a_second_device_attaching_again_gets_the_finished_note(
    rig: SimpleNamespace,
) -> None:
    rig.store.meeting = _meeting_row(state="ready", asr_job_id=JOB_ID)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready"
    assert rig.store.versions == []  # nothing written twice


def test_an_empty_transcript_writes_no_version_but_finishes_the_capture(
    rig: SimpleNamespace,
) -> None:
    # Silence, or a take the recorder threw away. The note is what the
    # author typed; a duplicate version would say nothing happened twice.
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content(user_notes="budget 40k"))

    async def _empty(job_id, *, auth_header):  # noqa: ANN001
        return {"language": "en", "segments": []}

    rig.monkeypatch.setattr(rig.module, "_fetch_transcript", _empty)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready"
    assert len(rig.store.versions) == 1  # nothing appended


def test_the_transcript_starts_the_engine_on_the_note(rig: SimpleNamespace) -> None:
    # Sprint 33 wired in: a meeting note writes itself exactly as a
    # from-transcript note does. Before this the meeting path only ever
    # put the transcript in a section — the Notes tab stayed empty.
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content())
    starts: list[dict] = []

    async def _start(conn, **kwargs):  # noqa: ANN001, ANN003
        starts.append(kwargs)
        return (uuid4(), "queued")

    rig.monkeypatch.setattr(rig.module.generation_service, "start", _start)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ready"
    assert len(starts) == 1
    assert starts[0]["note_id"] == NOTE_ID
    assert starts[0]["reason"] == "auto"
    assert starts[0]["transcript"]["segments"][0]["text"] == "The budget is fourteen thousand."


def test_an_engine_that_cannot_start_never_costs_the_capture(rig: SimpleNamespace) -> None:
    # No object store, no model, the workspace over budget: the transcript
    # is still in the note and the capture still finishes.
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content())

    async def _boom(conn, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("minio is down")

    rig.monkeypatch.setattr(rig.module.generation_service, "start", _boom)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ready"
    by_key = {s.section_key: s.text for s in rig.store.versions[-1].sections}
    assert by_key["discussion"] == "The budget is fourteen thousand."


def test_silence_starts_no_engine(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content())
    starts: list[dict] = []

    async def _start(conn, **kwargs):  # noqa: ANN001, ANN003
        starts.append(kwargs)
        return (uuid4(), "queued")

    async def _empty(job_id, *, auth_header):  # noqa: ANN001
        return {"language": "en", "segments": []}

    rig.monkeypatch.setattr(rig.module.generation_service, "start", _start)
    rig.monkeypatch.setattr(rig.module, "_fetch_transcript", _empty)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 200
    assert starts == []


def test_an_edit_racing_the_transcript_is_a_conflict_not_a_500(
    rig: SimpleNamespace,
) -> None:
    from note_service.domain.conflicts import OptimisticLockMismatchError

    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    rig.store.versions.append(_content())

    async def _raced(conn, **kwargs):  # noqa: ANN001, ANN003
        raise OptimisticLockMismatchError(current_version=7, expected_version=1)

    rig.monkeypatch.setattr(rig.module.repo, "append_version", _raced)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 409
    assert resp.json()["code"] == "note_changed"


def test_transcript_without_a_recording_is_a_conflict(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row()
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/transcript")
    assert resp.status_code == 409
    assert resp.json()["code"] == "no_job"


# ── State reads and the discard path ────────────────────────────────


def test_a_second_device_can_read_the_state(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row(state="transcribing", asr_job_id=JOB_ID)
    resp = rig.client.get(f"/v1/notes/{NOTE_ID}/meeting")
    assert resp.status_code == 200
    assert resp.json() == {
        "state": "transcribing",
        "asr_job_id": str(JOB_ID),
        "meeting_type": "auto",
        "started_at": "2026-09-20T09:00:00Z",
    }


def test_a_note_that_is_not_a_capture_has_no_meeting(rig: SimpleNamespace) -> None:
    resp = rig.client.get(f"/v1/notes/{NOTE_ID}/meeting")
    assert resp.status_code == 404


def test_discarding_the_recording_keeps_the_note(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row()
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/no-audio")
    assert resp.status_code == 200
    assert resp.json()["state"] == "no_audio"


def test_no_audio_never_undoes_a_finished_note(rig: SimpleNamespace) -> None:
    rig.store.meeting = _meeting_row(state="ready", asr_job_id=JOB_ID)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/meeting/no-audio")
    assert resp.json()["state"] == "ready"


# ── Another tenant ──────────────────────────────────────────────────


def test_another_tenants_note_is_a_404_on_every_route(rig: SimpleNamespace) -> None:
    rig.store.note = None
    rig.store.meeting = _meeting_row()
    rig.app.dependency_overrides[rig.deps.current_user] = lambda: _claims(sub=uuid4(), tid=uuid4())
    for method, path, body in (
        ("get", f"/v1/notes/{NOTE_ID}/meeting", None),
        ("put", f"/v1/notes/{NOTE_ID}/my-notes/timing", {"lines": []}),
        ("post", f"/v1/notes/{NOTE_ID}/meeting/job", {"asr_job_id": str(JOB_ID)}),
        ("post", f"/v1/notes/{NOTE_ID}/transcript", None),
        ("post", f"/v1/notes/{NOTE_ID}/meeting/no-audio", None),
    ):
        resp = getattr(rig.client, method)(path, **({"json": body} if body else {}))
        assert resp.status_code == 404, f"{path} → {resp.status_code}"
