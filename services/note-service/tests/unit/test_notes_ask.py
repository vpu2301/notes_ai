"""``POST /v1/notes/{id}/ask`` — "Ask this note".

Real handler, auth overridden, DB / asr-service / model boundaries stubbed.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from models import ConfigError, ErrorKind, ProviderError
from note_models import NoteContent, NoteStatus
from note_service.domain.ask import TRUNCATED_MARK, Turn, build_prompt
from note_service.domain.notes_repository import NoteRow, VersionRow

TENANT = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMBER = UUID("11111111-1111-1111-1111-111111111111")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
JOB_ID = UUID("99999999-9999-9999-9999-999999999999")


def _member_claims() -> Claims:
    return Claims(
        sub=MEMBER,
        tid=TENANT,
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note() -> NoteRow:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    return NoteRow(
        id=NOTE_ID,
        tenant_id=TENANT,
        code="NOTE-2026-00032",
        status=NoteStatus.DRAFT,
        current_version_id=VERSION_ID,
        current_version_number=2,
        primary_author_id=MEMBER,
        co_author_ids=[],
        title="Weekend plans",
        created_at=now,
        updated_at=now,
        finalized_at=None,
        cancelled_at=None,
    )


def _version() -> VersionRow:
    content = NoteContent.model_validate(
        {
            "template_id": "ada45115-5436-4374-97d7-bc0486920f25",
            "template_schema_version": 1,
            "title": "Weekend plans",
            "sections": [
                {"section_key": "attendees", "text": "Liliia: TK Maxx first, then cake."},
                {"section_key": "decisions", "text": ""},
            ],
        }
    )
    return VersionRow(
        id=VERSION_ID,
        note_id=NOTE_ID,
        version_number=2,
        parent_version_id=None,
        created_by=MEMBER,
        created_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        content=content,
        rendered_text="",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


class _FakeProvider:
    backend = "recorded"
    model_id = "fake-1"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail: Exception | None = None

    async def complete(self, prompt, schema=None, *, max_tokens, temperature=0.0, system=None):  # noqa: ANN001
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            text="  Cake after TK Maxx.  ",
            backend=self.backend,
            model_id=self.model_id,
            input_tokens=120,
            output_tokens=8,
            latency_ms=42,
        )

    async def probe(self) -> None: ...

    async def aclose(self) -> None: ...


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_ask as mod

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))  # type: ignore[arg-type]
    )

    conn = SimpleNamespace()
    source_job: dict[str, UUID | None] = {"id": JOB_ID}

    async def _fetchval(query, *args):  # noqa: ANN001, ANN002
        assert "source_asr_job_id" in query
        return source_job["id"]

    conn.fetchval = _fetchval

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield conn

    monkeypatch.setattr(mod, "tenant_connection", _fake_tenant_conn)

    notes: dict[UUID, NoteRow | None] = {NOTE_ID: _note()}

    async def _fetch_note(conn, *, note_id, include_deleted=False):  # noqa: ANN001
        return notes.get(note_id)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return _version()

    monkeypatch.setattr(mod.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(mod.repo, "fetch_version", _fetch_version)

    transcript_calls: list[UUID] = []

    async def _fetch_transcript(job_id, *, auth_header):  # noqa: ANN001
        transcript_calls.append(job_id)
        return {
            "speakers": ["SPEAKER_1"],
            "turns": [
                {"speaker": None, "name": None, "paragraphs": ["Shall we go out?"]},
                {"speaker": "SPEAKER_1", "name": "Liliia", "paragraphs": ["TK Maxx, then cake."]},
            ],
        }

    monkeypatch.setattr(mod, "_fetch_transcript", _fetch_transcript)

    provider = _FakeProvider()
    monkeypatch.setattr(mod, "_asker", None)
    asker = mod.get_asker()
    monkeypatch.setattr(asker, "_provider", lambda workspace_id: provider)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    return SimpleNamespace(
        client=TestClient(app),
        provider=provider,
        audit_calls=audit_calls,
        transcript_calls=transcript_calls,
        notes=notes,
        source_job=source_job,
        module=mod,
    )


def test_ask_answers_from_note_and_transcript(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/ask",
        json={
            "question": "  What did   Liliia suggest? ",
            "history": [
                {"role": "user", "text": "Who was there?"},
                {"role": "assistant", "text": "Liliia and one unnamed speaker."},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "answer": "Cake after TK Maxx.",
        "backend": "recorded",
        "model_id": "fake-1",
    }

    (call,) = rig.provider.calls
    prompt = call["prompt"]
    assert "# Note: Weekend plans (NOTE-2026-00032)" in prompt
    assert "## Attendees\nLiliia: TK Maxx first, then cake." in prompt
    assert "## Decisions" not in prompt  # empty sections are skipped
    assert (
        "# Transcript\nUnknown speaker: Shall we go out?\n\nLiliia: TK Maxx, then cake." in prompt
    )
    assert (
        "# Conversation so far\nUser: Who was there?\nAssistant: Liliia and one unnamed speaker."
        in prompt
    )
    assert prompt.endswith("# Question\nWhat did Liliia suggest?")
    assert call["system"] and "meeting-notes app" in call["system"]
    assert rig.transcript_calls == [JOB_ID]

    (event,) = rig.audit_calls
    assert event["kind"] == "note.asked"
    assert event["payload"]["backend"] == "recorded"
    assert event["payload"]["question_chars"] == len("What did Liliia suggest?")
    assert event["payload"]["with_transcript"] is True
    # Content never reaches the audit chain.
    assert "Liliia" not in str(event["payload"])


def test_ask_without_recording_uses_note_alone(rig: SimpleNamespace) -> None:
    rig.source_job["id"] = None
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/ask", json={"question": "Any decisions?"})
    assert resp.status_code == 200
    assert rig.transcript_calls == []
    assert "# Transcript" not in rig.provider.calls[0]["prompt"]
    assert rig.audit_calls[0]["payload"]["with_transcript"] is False


def test_ask_survives_transcript_fetch_failure(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    async def _gone(job_id, *, auth_header):  # noqa: ANN001
        raise HTTPException(410, detail={"error": "transcript_erased"})

    monkeypatch.setattr(rig.module, "_fetch_transcript", _gone)
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/ask", json={"question": "Summarize"})
    assert resp.status_code == 200
    assert "# Transcript" not in rig.provider.calls[0]["prompt"]


def test_ask_unknown_note_is_404(rig: SimpleNamespace) -> None:
    other = UUID("44444444-4444-4444-4444-444444444444")
    resp = rig.client.post(f"/v1/notes/{other}/ask", json={"question": "Hi?"})
    assert resp.status_code == 404
    assert rig.provider.calls == []


def test_ask_rejects_blank_question(rig: SimpleNamespace) -> None:
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/ask", json={"question": "   "})
    assert resp.status_code == 422


def test_ask_model_not_configured_is_503(rig: SimpleNamespace) -> None:
    rig.provider.fail = ConfigError("missing_env", "backend 'hf_eu' needs HF_TOKEN")
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/ask", json={"question": "Hi?"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "model_not_configured"
    assert "No model" in resp.json()["detail"]
    assert rig.audit_calls == []


def test_ask_provider_failure_is_503_with_kind(rig: SimpleNamespace) -> None:
    rig.provider.fail = ProviderError(ErrorKind.TIMEOUT, "slow", backend="dev_mac")
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/ask", json={"question": "Hi?"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "model_unavailable"
    assert body["kind"] == str(ErrorKind.TIMEOUT)


def test_build_prompt_clips_transcript_not_note() -> None:
    prompt = build_prompt(
        title="T",
        code="NOTE-1",
        sections=[("Notes", "keep me " * 20)],
        transcript="word " * 2000,
        history=[Turn(role="user", text="  ")],
        question="q",
        max_chars=600,
    )
    assert "keep me keep me" in prompt
    assert TRUNCATED_MARK in prompt
    assert len(prompt) < 900
    assert "# Conversation so far" not in prompt  # blank history turns are dropped
