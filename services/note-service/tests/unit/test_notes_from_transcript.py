"""Create-from-transcript surface: template auto-match + POST /v1/notes/from-transcript.

Mirrors ``test_notes_create``: real handlers, auth overridden, DB /
asr-service boundaries stubbed — no infra required.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain.template_match import (
    TemplateCandidate,
    select_template,
)
from template_models import TemplateDefinition

REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("99999999-9999-9999-9999-999999999999")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")

INTERVIEW_TRANSCRIPT = (
    "Співбесіда з кандидатом на позицію інженера.\n"
    "Кандидат впевнено відповідав на технічні питання.\n"
    "Висновок: рекомендую наступний етап співбесіди."
)


def _definition(
    code: str, name: str, category: str, sections: list[tuple[str, str]]
) -> TemplateDefinition:
    return TemplateDefinition.model_validate(
        {
            "code": code,
            "name": name,
            "language": "uk",
            "category": category,
            "sections": [
                {
                    "id": sid,
                    "name": sname,
                    "asr_prompt": sname,
                    "order": i,
                }
                for i, (sid, sname) in enumerate(sections)
            ],
        }
    )


def _candidate(code: str, name: str, category: str) -> TemplateCandidate:
    return TemplateCandidate(
        id=uuid4(),
        code=code,
        name=name,
        category=category,
        schema_version=1,
        definition=_definition(
            code, name, category, [("notes", "Нотатки"), ("conclusion", "Висновок")]
        ),
        is_system=True,
    )


CATALOGUE = [
    _candidate("interview_debrief_uk", "Співбесіда з кандидатом", "hr"),
    _candidate("sales_call_uk", "Дзвінок із клієнтом", "sales"),
    _candidate("meeting_notes_uk", "Нотатки зустрічі", "general"),
    _candidate("project_update_uk", "Статус проєкту", "general"),
]


# ── Auto-match (pure) ───────────────────────────────────────────────


def test_interview_transcript_matches_interview_template() -> None:
    choice = select_template(CATALOGUE, INTERVIEW_TRANSCRIPT)
    assert choice is not None
    assert choice.candidate.code == "interview_debrief_uk"
    assert choice.mode == "auto"
    assert choice.score >= 3


def test_unrelated_transcript_falls_back_to_meeting_notes() -> None:
    choice = select_template(CATALOGUE, "обговорили погоду і плани")
    assert choice is not None
    assert choice.candidate.code == "meeting_notes_uk"
    assert choice.mode == "fallback"


def test_empty_catalogue_returns_none() -> None:
    assert select_template([], INTERVIEW_TRANSCRIPT) is None


def test_inflected_form_still_matches() -> None:
    # «співбесіди» (genitive) must match template «Співбесіда з кандидатом».
    choice = select_template(CATALOGUE, "після співбесіди кандидат надіслав тестове завдання")
    assert choice is not None
    assert choice.candidate.code == "interview_debrief_uk"
    assert choice.mode == "auto"


# ── Endpoint ────────────────────────────────────────────────────────


def _member_claims() -> Claims:
    return Claims(
        sub=REQUESTER_SUB,
        tid=uuid4(),
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _transcript_result() -> dict:
    return {
        "job_id": str(JOB_ID),
        "language": "uk",
        "nlp_applied": True,
        "segments": [
            {"text": "Співбесіда з кандидатом на позицію інженера.", "raw_text": "…"},
            {"text": "Висновок: рекомендую наступний етап.", "raw_text": "…"},
        ],
    }


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_from_transcript as rft

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    fake_state = SimpleNamespace(
        app_pool=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
    )
    deps.install_state(fake_state)  # type: ignore[arg-type]

    conn = SimpleNamespace()
    existing_notes: dict[UUID, dict] = {}

    async def _fetchrow(query, *args):  # noqa: ANN001, ANN002
        row = existing_notes.get(args[0])
        return row

    conn.fetchrow = _fetchrow

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield conn

    monkeypatch.setattr(rft, "tenant_connection", _fake_tenant_conn)

    async def _fetch_transcript(job_id, *, auth_header):  # noqa: ANN001
        return _transcript_result()

    monkeypatch.setattr(rft, "_fetch_transcript", _fetch_transcript)

    async def _load_candidates(conn, *, language):  # noqa: ANN001
        return CATALOGUE

    monkeypatch.setattr(rft.template_match, "load_candidates", _load_candidates)

    async def _next_code(conn, *, tenant_id):  # noqa: ANN001
        return "NOTE-2026-00042"

    monkeypatch.setattr(rft.code_sequence, "next_code", _next_code)

    async def _extract_fields(**kwargs):  # noqa: ANN003
        return {}

    monkeypatch.setattr(rft, "extract_fields", _extract_fields)

    create_calls: list[dict] = []

    async def _create(conn, **kwargs):  # noqa: ANN001, ANN003
        create_calls.append(kwargs)
        return NOTE_ID, VERSION_ID

    monkeypatch.setattr(rft.repo, "create_note_with_v1", _create)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    return SimpleNamespace(
        client=TestClient(app),
        create_calls=create_calls,
        audit_calls=audit_calls,
        existing_notes=existing_notes,
        module=rft,
        monkeypatch=monkeypatch,
    )


def test_assign_auto_selects_template_and_creates_note(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        "/v1/notes/from-transcript",
        json={"asr_job_id": str(JOB_ID)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["template_selection"] == "auto"
    assert body["template_name"] == "Співбесіда з кандидатом"
    assert body["code"] == "NOTE-2026-00042"

    (call,) = rig.create_calls
    assert call["source_asr_job_id"] == JOB_ID
    content = call["content"]
    # Transcript lands in the FIRST free-text section; the rest stay default.
    assert content.sections[0].section_key == "notes"
    # Sentences joined with a space (not a newline the editor would drop),
    # so periods keep a following space rather than gluing.
    assert (
        content.sections[0].text
        == "Співбесіда з кандидатом на позицію інженера. Висновок: рекомендую наступний етап."
    )
    assert content.sections[1].text == ""

    (event,) = rig.audit_calls
    assert event["payload"]["source_asr_job_id"] == str(JOB_ID)
    assert event["payload"]["template_selection"] == "auto"


def test_assign_duplicate_job_conflicts(rig: SimpleNamespace) -> None:
    rig.existing_notes[JOB_ID] = {"id": NOTE_ID, "code": "NOTE-2026-00001"}
    resp = rig.client.post(
        "/v1/notes/from-transcript",
        json={"asr_job_id": str(JOB_ID)},
    )
    assert resp.status_code == 409
    assert "already_assigned" in resp.text
    assert rig.create_calls == []


def test_assign_passes_through_not_ready_409(rig: SimpleNamespace) -> None:
    async def _not_ready(job_id, *, auth_header):  # noqa: ANN001
        raise HTTPException(409, detail={"job_status": "running"})

    rig.monkeypatch.setattr(rig.module, "_fetch_transcript", _not_ready)
    resp = rig.client.post(
        "/v1/notes/from-transcript",
        json={"asr_job_id": str(JOB_ID)},
    )
    assert resp.status_code == 409
    assert rig.create_calls == []


# ── Diarized (ambient capture) rendering ────────────────────────────


def _diarized_result() -> dict:
    return {
        "job_id": str(JOB_ID),
        "language": "uk",
        "nlp_applied": True,
        "speakers": ["SPEAKER_1", "SPEAKER_2"],
        "segments": [
            {"text": "Почнімо з підсумків спринту.", "speaker": "SPEAKER_1"},
            {"text": "Реліз готовий.", "speaker": "SPEAKER_1"},
            {"text": "Коли деплой?", "speaker": "SPEAKER_2"},
            {"text": "Завтра вранці.", "speaker": "SPEAKER_1"},
            {"text": "(нерозбірливо)", "speaker": None},
        ],
    }


def test_transcript_text_renders_dialogue_when_diarized() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    # Contiguous same-speaker segments merge into ONE turn line; an
    # unattributed segment renders under UNKNOWN, never merged into a
    # neighbouring speaker (mirrors dictation-service dialogue_text).
    assert _transcript_text(_diarized_result()) == (
        "Speaker 1: Почнімо з підсумків спринту. Реліз готовий.\n\n"
        "Speaker 2: Коли деплой?\n\n"
        "Speaker 1: Завтра вранці.\n\n"
        "Unknown speaker: (нерозбірливо)"
    )


def test_transcript_text_flat_when_not_diarized() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    # The pre-ambient shape (no speakers / no speaker keys) is unchanged:
    # space-joined flat prose.
    assert _transcript_text(_transcript_result()) == (
        "Співбесіда з кандидатом на позицію інженера. Висновок: рекомендую наступний етап."
    )


def test_transcript_text_dialogue_without_speaker_roster() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    # Segment-level labels alone are enough to trigger dialogue rendering.
    result = {
        "segments": [
            {"text": "Один.", "speaker": "SPEAKER_1"},
            {"text": "Два.", "speaker": "SPEAKER_2"},
        ]
    }
    assert _transcript_text(result) == "Speaker 1: Один.\n\nSpeaker 2: Два."


def test_assign_diarized_job_creates_dialogue_note(rig: SimpleNamespace) -> None:
    async def _fetch_diarized(job_id, *, auth_header):  # noqa: ANN001
        return _diarized_result()

    rig.monkeypatch.setattr(rig.module, "_fetch_transcript", _fetch_diarized)
    resp = rig.client.post(
        "/v1/notes/from-transcript",
        json={"asr_job_id": str(JOB_ID)},
    )
    assert resp.status_code == 201, resp.text

    (call,) = rig.create_calls
    content = call["content"]
    text = content.sections[0].text
    assert text.startswith("Speaker 1: Почнімо з підсумків спринту.")
    assert "Speaker 2: Коли деплой?" in text
    assert "Unknown speaker: (нерозбірливо)" in text
    # Speaker labels stay neutral — no name inference server-side.
    assert "Speaker 3" not in text


def test_by_source_job_bulk_lookup(rig: SimpleNamespace) -> None:
    async def _fetch_links(conn, *, asr_job_ids):  # noqa: ANN001
        assert asr_job_ids == [JOB_ID]
        return [
            {
                "source_asr_job_id": JOB_ID,
                "id": NOTE_ID,
                "code": "NOTE-2026-00042",
                "status": "draft",
            }
        ]

    rig.monkeypatch.setattr(rig.module.repo, "fetch_notes_by_source_jobs", _fetch_links)
    resp = rig.client.get(f"/v1/notes/by-source-job?ids={JOB_ID}")
    assert resp.status_code == 200
    (link,) = resp.json()
    assert link["note_id"] == str(NOTE_ID)
    assert link["asr_job_id"] == str(JOB_ID)


# ── Server-side turns (asr-service ``turns`` + ``speaker_names``) ────


def _structured_result() -> dict:
    return {
        "job_id": str(JOB_ID),
        "language": "en",
        "segments": [
            {"text": "Let's start with the numbers.", "speaker": "SPEAKER_1"},
            {"text": "Which numbers?", "speaker": "SPEAKER_2"},
        ],
        "speakers": ["SPEAKER_1", "SPEAKER_2"],
        "speaker_names": {"SPEAKER_1": "Mark", "SPEAKER_2": "Speaker 2"},
        "turns": [
            {
                "speaker": "SPEAKER_1",
                "name": "Mark",
                "start_ms": 0,
                "end_ms": 9000,
                "paragraphs": ["Let's start with the numbers.", "Revenue is up, costs are flat."],
            },
            {
                "speaker": "SPEAKER_2",
                "name": "Speaker 2",
                "start_ms": 9000,
                "end_ms": 10_000,
                "paragraphs": ["Which numbers?"],
            },
            {
                "speaker": None,
                "name": None,
                "start_ms": 10_000,
                "end_ms": 10_500,
                "paragraphs": ["(crosstalk)"],
            },
        ],
    }


def test_transcript_text_prefers_server_turns_with_names_and_paragraphs() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    assert _transcript_text(_structured_result()) == (
        "Mark: Let's start with the numbers.\n"
        "Revenue is up, costs are flat.\n\n"
        "Speaker 2: Which numbers?\n\n"
        "Unknown speaker: (crosstalk)"
    )


def test_transcript_text_undiarized_turns_render_as_plain_paragraphs() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    result = {
        "segments": [{"text": "One."}, {"text": "Two."}],
        "turns": [
            {
                "speaker": None,
                "name": None,
                "start_ms": 0,
                "end_ms": 5000,
                "paragraphs": ["One.", "Two."],
            }
        ],
    }
    assert _transcript_text(result) == "One.\nTwo."


def test_dialogue_fallback_uses_speaker_names_when_present() -> None:
    from note_service.routers.notes_from_transcript import _transcript_text

    result = {
        "segments": [
            {"text": "Hi.", "speaker": "SPEAKER_1"},
            {"text": "Hello.", "speaker": "SPEAKER_2"},
        ],
        "speaker_names": {"SPEAKER_1": "Mark"},
    }
    assert _transcript_text(result) == "Mark: Hi.\n\nSpeaker 2: Hello."
