"""Instructions for one note — "Write this note differently" (Sprint N4), stored as
written since Sprint R0."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteStatus
from note_service.domain import note_instructions_repository as repo
from note_service.domain.notes_repository import NoteRow

TENANT_A = UUID("22222222-2222-2222-2222-222222222222")
TENANT_B = UUID("33333333-3333-3333-3333-333333333333")
AUTHOR = UUID("44444444-4444-4444-4444-444444444444")
OTHER = UUID("55555555-5555-5555-5555-555555555555")
NOTE = uuid4()
JOB = uuid4()
WORKSPACE_TEXT = "Short. Four summary sentences at most."
CLIENT_TEXT = "Keep topic sections."
NOTE_TEXT = "One paragraph, no sections, for the Quillhaven CFO."


def _claims(sub: UUID, roles: list[str], tenant: UUID = TENANT_A) -> Claims:
    return Claims(sub=sub, tid=tenant, roles=roles, sid="s", iss="https://test/issuer", aud="mdx",
                  exp=9_999_999_999, iat=1_700_000_000)  # fmt: skip


def _note(status: NoteStatus = NoteStatus.DRAFT, job: UUID | None = JOB) -> NoteRow:
    now = datetime.now(UTC)
    return NoteRow(
        id=NOTE, tenant_id=TENANT_A, code="NOTE-2026-00001", status=status,
        current_version_id=uuid4(), current_version_number=1, primary_author_id=AUTHOR,
        co_author_ids=[], title="t", created_at=now, updated_at=now, finalized_at=None,
        cancelled_at=None, visibility="workspace", collaborators={}, source_asr_job_id=job,
    )  # fmt: skip


def _parent(scope: str, text: str, version: int) -> repo.Row:
    now = datetime.now(UTC)
    return repo.Row(
        tenant_id=TENANT_A, scope=scope, version=version, text=text, profile={}, profile_hash="",
        compile_status="compiled", compile_error_kind=None, compiler_version="none", backend=None,
        updated_by=AUTHOR, created_at=now, updated_at=now,
    )  # fmt: skip


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_instructions as workspace_mod
    from note_service.routers import note_instructions as mod

    caplog.set_level(logging.DEBUG)
    audit: list[dict] = []
    note = {"row": _note()}
    stored: dict[UUID, repo.NoteRow] = {}
    current = {"tenant": TENANT_A}

    async def _write_event(**kwargs: Any) -> None:
        audit.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
        )
    )

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        current["tenant"] = tenant_id
        yield None

    async def _fetch_note(conn: Any, *, note_id: UUID, **_: Any) -> Any:
        # RLS: tenant B sees no note of tenant A.
        return note["row"] if current["tenant"] == TENANT_A and note_id == NOTE else None

    async def _fetch_many(conn: Any, *, tenant_id: UUID, scopes: Any) -> dict[str, repo.Row]:
        parents = {
            "workspace": _parent("workspace", WORKSPACE_TEXT, 3),
            "client": _parent("client", CLIENT_TEXT, 1),
        }
        return {s: parents[s] for s in scopes if s in parents}

    async def _get_note_row(conn: Any, *, note_id: UUID) -> Any:
        return stored.get(note_id)

    async def _upsert_note(conn: Any, **kw: Any) -> repo.NoteRow:
        now = datetime.now(UTC)
        fields = {k: kw[k] for k in ("tenant_id", "note_id", "text", "profile", "profile_hash",
                  "compile_status", "compile_error_kind", "compiler_version", "base_versions", "updated_by")}  # fmt: skip
        stored[kw["note_id"]] = repo.NoteRow(**fields, created_at=now, updated_at=now)
        return stored[kw["note_id"]]

    async def _delete_note(conn: Any, *, note_id: UUID) -> bool:
        return stored.pop(note_id, None) is not None

    async def _meeting(conn: Any, *, note_id: UUID) -> Any:
        return SimpleNamespace(meeting_type="client")

    monkeypatch.setattr(mod, "tenant_connection", _conn)
    monkeypatch.setattr(mod.notes_repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(mod.repo, "fetch_many", _fetch_many)
    monkeypatch.setattr(mod.repo, "fetch_note", _get_note_row)
    monkeypatch.setattr(mod.repo, "upsert_note", _upsert_note)
    monkeypatch.setattr(mod.repo, "delete_note", _delete_note)
    monkeypatch.setattr(mod.meetings, "fetch", _meeting)
    monkeypatch.setattr(workspace_mod.settings, "note_instructions_enabled", True)

    app = create_app()

    def as_(claims: Claims) -> None:
        app.dependency_overrides[deps.current_user] = lambda: claims

    as_(_claims(AUTHOR, ["member"]))
    yield SimpleNamespace(client=TestClient(app), as_=as_, audit=audit, note=note,
                          stored=stored, caplog=caplog)  # fmt: skip
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


URL = f"/v1/notes/{NOTE}/instructions"


def test_an_editor_saves_against_the_parents(api: Any) -> None:
    r = api.client.put(URL, json={"text": NOTE_TEXT})
    assert r.status_code == 201
    body = r.json()
    assert body["scope"] == "note" and body["base_versions"] == {"workspace": 3, "client": 1}
    assert body["extends"] == {"scope": "client", "version": 1}
    assert body["understood"] == [] and body["profile"] == {}
    assert api.client.get(URL).json()["text"] == NOTE_TEXT


def test_empty_text_removes_and_delete_is_idempotent(api: Any) -> None:
    api.client.put(URL, json={"text": NOTE_TEXT})
    assert api.client.put(URL, json={"text": "  "}).json()["version"] == 0 and api.stored == {}
    assert api.client.delete(URL).status_code == 204


def test_a_viewer_is_refused_and_another_workspace_sees_nothing(api: Any) -> None:
    api.as_(_claims(OTHER, ["viewer"]))
    assert api.client.get(URL).status_code == 403
    assert api.client.put(URL, json={"text": NOTE_TEXT}).status_code == 403
    api.as_(_claims(AUTHOR, ["member"], tenant=TENANT_B))
    for call in (lambda: api.client.get(URL), lambda: api.client.put(URL, json={"text": "x"}),
                 lambda: api.client.delete(URL)):  # fmt: skip
        assert call().status_code == 404


def test_a_note_that_cannot_be_rewritten_is_refused(api: Any) -> None:
    api.note["row"] = _note(job=None)
    r = api.client.put(URL, json={"text": NOTE_TEXT})
    assert r.status_code == 409 and r.json()["code"] == "no_transcript"
    api.note["row"] = _note(status=NoteStatus.CANCELLED)
    assert api.client.put(URL, json={"text": NOTE_TEXT}).json()["code"] == "note_cancelled"
    assert api.stored == {}


def test_the_preview_route_is_gone(api: Any) -> None:
    assert api.client.post(f"{URL}/preview", json={"text": NOTE_TEXT}).status_code in (404, 405)
    assert api.stored == {}


def test_no_text_reaches_logs_or_audit(api: Any) -> None:
    api.client.put(URL, json={"text": NOTE_TEXT})
    api.client.put(URL, json={"text": ""})
    assert "Quillhaven" not in api.caplog.text
    assert "Quillhaven" not in json.dumps([a["payload"] for a in api.audit], default=str)
    assert [a["kind"] for a in api.audit] == [
        "note.instructions_changed",
        "note.instructions_cleared",
    ]
