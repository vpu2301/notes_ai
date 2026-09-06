"""GET /v1/notes/{id}: who must declare a read purpose, and what they get.

The author team and people the note was shared with read without a
purpose. An oversight reader — a tenant_admin on a colleague's private
note here — must send ``?purpose=``; without it the answer is a flat RFC
9457 problem the clients branch on, and with it the envelope names the
author so the client can say whose note it is showing.

Exercises the real ``notes.get_note`` handler with the auth dependency
overridden and the DB/audit boundary stubbed (mirrors
``test_notes_section_labels``).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteSection, NoteStatus

REQUESTER_SUB = UUID("11111111-1111-1111-1111-111111111111")
OTHER_AUTHOR = UUID("22222222-2222-2222-2222-222222222222")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
TEMPLATE_ID = UUID("44444444-4444-4444-4444-444444444444")

MISSING_PURPOSE = "https://errors.notes-ai/missing-read-purpose"


def _claims(*roles: str) -> Claims:
    return Claims(
        sub=REQUESTER_SUB,
        tid=uuid4(),
        roles=list(roles),
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note_row(*, primary_author_id: UUID, visibility: str = "private"):
    from note_service.domain.notes_repository import NoteRow

    now = datetime(2026, 5, 20, tzinfo=UTC)
    return NoteRow(
        id=NOTE_ID,
        tenant_id=uuid4(),
        code="R-0001",
        status=NoteStatus.DRAFT,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=primary_author_id,
        co_author_ids=[],
        title="Weekly sync",
        created_at=now,
        updated_at=now,
        finalized_at=None,
        cancelled_at=None,
        visibility=visibility,
    )


def _version_row():
    from note_service.domain.notes_repository import VersionRow

    return VersionRow(
        id=uuid4(),
        note_id=NOTE_ID,
        version_number=1,
        parent_version_id=None,
        created_by=OTHER_AUTHOR,
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
        content=NoteContent(
            template_id=TEMPLATE_ID,
            template_schema_version=1,
            sections=[NoteSection(section_key="summary", text="...")],
        ),
        rendered_text="rendered body",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    """Build a client for a given requester and note; records audit + member lookups."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.domain import repository
    from note_service.main import create_app
    from note_service.routers import notes

    def _build(*, claims: Claims, note) -> TestClient:  # noqa: ANN001
        audit_calls: list[dict] = []
        member_lookups: list[list[UUID]] = []

        async def _write_event(**kwargs):  # noqa: ANN003
            audit_calls.append(kwargs)

        deps.install_state(
            SimpleNamespace(
                app_pool=object(),
                audit_writer=SimpleNamespace(write_event=_write_event),
            )  # type: ignore[arg-type]
        )

        @contextlib.asynccontextmanager
        async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
            yield None

        async def _fetch_note(conn, *, note_id):  # noqa: ANN001
            return note

        async def _fetch_version(conn, *, version_id):  # noqa: ANN001
            return _version_row()

        async def _fetch_members(conn, *, subs):  # noqa: ANN001
            from note_service.domain.notes_repository import MemberRow

            member_lookups.append(list(subs))
            return [MemberRow(sub=s, email="ada@example.com", display_name="Ada") for s in subs]

        async def _get_template(conn, *, template_id):  # noqa: ANN001
            return None  # labels fall back to nothing; not under test here

        monkeypatch.setattr(notes, "tenant_connection", _fake_tenant_conn)
        monkeypatch.setattr(notes.repo, "fetch_note", _fetch_note)
        monkeypatch.setattr(notes.repo, "fetch_version", _fetch_version)
        monkeypatch.setattr(notes.repo, "fetch_members", _fetch_members)
        monkeypatch.setattr(repository, "get_template", _get_template)

        app = create_app()
        app.dependency_overrides[deps.current_user] = lambda: claims
        c = TestClient(app)
        c.audit_calls = audit_calls  # type: ignore[attr-defined]
        c.member_lookups = member_lookups  # type: ignore[attr-defined]
        return c

    return _build


def test_author_reads_without_purpose(make_client) -> None:  # noqa: ANN001
    client = make_client(claims=_claims("member"), note=_note_row(primary_author_id=REQUESTER_SUB))
    resp = client.get(f"/v1/notes/{NOTE_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_author_id"] == str(REQUESTER_SUB)
    # Authors know whose note it is; no lookup, no name.
    assert body["primary_author_name"] is None
    assert client.member_lookups == []
    assert client.audit_calls[-1]["payload"] == {"purpose": "author", "is_author": True}


def test_admin_without_purpose_gets_a_flat_problem(make_client) -> None:  # noqa: ANN001
    client = make_client(
        claims=_claims("tenant_admin", "member"), note=_note_row(primary_author_id=OTHER_AUTHOR)
    )
    resp = client.get(f"/v1/notes/{NOTE_ID}")
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    # Top-level members, not a dict nested under `detail`.
    assert body["type"] == MISSING_PURPOSE
    assert body["title"] == "Read purpose required"
    assert isinstance(body["detail"], str) and "?purpose=" in body["detail"]
    assert "review" in body["allowed"]
    # A refused read is not a read: nothing in the audit trail.
    assert client.audit_calls == []


def test_admin_with_purpose_is_named_the_author(make_client) -> None:  # noqa: ANN001
    client = make_client(
        claims=_claims("tenant_admin", "member"), note=_note_row(primary_author_id=OTHER_AUTHOR)
    )
    resp = client.get(f"/v1/notes/{NOTE_ID}", params={"purpose": "review"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_author_id"] == str(OTHER_AUTHOR)
    assert body["primary_author_name"] == "Ada"
    assert client.member_lookups == [[OTHER_AUTHOR]]
    assert client.audit_calls[-1]["payload"] == {"purpose": "review", "is_author": False}


def test_shared_with_reads_as_collaborator(make_client) -> None:  # noqa: ANN001
    note = _note_row(primary_author_id=OTHER_AUTHOR)
    note.shared_with_ids = [REQUESTER_SUB]
    client = make_client(claims=_claims("member"), note=note)
    resp = client.get(f"/v1/notes/{NOTE_ID}")
    assert resp.status_code == 200
    assert resp.json()["primary_author_name"] is None


def test_member_on_a_private_note_is_a_404_not_a_422(make_client) -> None:  # noqa: ANN001
    client = make_client(claims=_claims("member"), note=_note_row(primary_author_id=OTHER_AUTHOR))
    assert client.get(f"/v1/notes/{NOTE_ID}").status_code == 404
    assert client.get(f"/v1/notes/{NOTE_ID}", params={"purpose": "review"}).status_code == 404


def test_member_on_a_workspace_note_declares_a_purpose(make_client) -> None:  # noqa: ANN001
    client = make_client(
        claims=_claims("member"),
        note=_note_row(primary_author_id=OTHER_AUTHOR, visibility="workspace"),
    )
    assert client.get(f"/v1/notes/{NOTE_ID}").json()["type"] == MISSING_PURPOSE
    resp = client.get(f"/v1/notes/{NOTE_ID}", params={"purpose": "collaboration"})
    assert resp.status_code == 200
    assert resp.json()["primary_author_name"] == "Ada"
