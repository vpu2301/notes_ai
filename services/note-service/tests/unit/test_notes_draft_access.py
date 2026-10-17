"""W3: PUT /v1/notes/{id}/draft needs `edit` on the note (require_edit). Real handler, DB stubbed."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteContent, NoteSection, NoteStatus
from note_service.domain.notes_repository import NoteRow, VersionRow

AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
CALLER = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("33333333-3333-3333-3333-333333333333")
TEMPLATE = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _claims(*roles: str) -> Claims:
    return Claims(
        sub=CALLER,
        tid=uuid4(),
        roles=list(roles),
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _content(text: str) -> NoteContent:
    return NoteContent(
        template_id=TEMPLATE,
        template_schema_version=1,
        sections=[NoteSection(section_key="summary", text=text)],
    )


def _note(visibility: str, collaborators: dict[UUID, str]) -> NoteRow:
    return NoteRow(
        id=NOTE,
        tenant_id=uuid4(),
        code="NOTE-2026-00001",
        status=NoteStatus.DRAFT,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        title="t",
        created_at=NOW,
        updated_at=NOW,
        finalized_at=None,
        cancelled_at=None,
        visibility=visibility,
        collaborators=collaborators,
    )


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_drafts as router_mod

    def _build(*, claims: Claims, note: NoteRow) -> TestClient:
        appended: list[dict] = []

        class _NoLimit:
            async def check_and_record(self, *, note_id):  # noqa: ANN001
                return True, 0

        class _Buffer:
            async def record(self, **kwargs):  # noqa: ANN003
                return None

        async def _write_event(**kwargs):  # noqa: ANN003
            return None

        deps.install_state(  # type: ignore[arg-type]
            SimpleNamespace(
                app_pool=object(),
                audit_writer=SimpleNamespace(write_event=_write_event),
                autosave_rate_limiter=_NoLimit(),
                draft_audit_buffer=_Buffer(),
            )
        )

        @contextlib.asynccontextmanager
        async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
            yield None

        async def _lock(conn, *, note_id):  # noqa: ANN001
            return note if note_id == NOTE else None

        async def _fetch_version(conn, *, version_id):  # noqa: ANN001
            return VersionRow(
                id=version_id,
                note_id=NOTE,
                version_number=1,
                parent_version_id=None,
                created_by=AUTHOR,
                created_at=NOW,
                content=_content("before"),
                rendered_text="before",
                body_hash="old",
                is_amendment=False,
                amendment_type=None,
                amendment_reason=None,
            )

        async def _append(conn, **kwargs):  # noqa: ANN001, ANN003
            appended.append(kwargs)
            return uuid4(), 2

        async def _no_check(conn, *, content):  # noqa: ANN001
            return None

        async def _no_types(conn, *, content):  # noqa: ANN001
            return {}

        monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)
        monkeypatch.setattr(router_mod.repo, "lock_note_for_update", _lock)
        monkeypatch.setattr(router_mod.repo, "fetch_version", _fetch_version)
        monkeypatch.setattr(router_mod.repo, "append_version", _append)
        monkeypatch.setattr(router_mod, "ensure_valid_field_metadata", _no_check)
        monkeypatch.setattr(router_mod, "template_field_types", _no_types)

        app = create_app()
        app.dependency_overrides[deps.current_user] = lambda: claims
        c = TestClient(app)
        c.appended = appended  # type: ignore[attr-defined]
        return c

    return _build


def _put(client: TestClient):  # noqa: ANN202
    return client.put(
        f"/v1/notes/{NOTE}/draft",
        json={"expected_version": 1, "content": _content("after").model_dump(mode="json")},
    )


@pytest.mark.parametrize(
    ("roles", "visibility", "collaborators"),
    [
        (("member",), "private", {CALLER: "comment"}),  # comment collaborator
        (("member",), "private", {CALLER: "view"}),  # view collaborator
        (("guest",), "private", {CALLER: "view"}),  # guest with a view grant
        (("guest",), "workspace", {CALLER: "comment"}),  # visibility gives a guest nothing
    ],
)
def test_draft_below_edit_is_403_insufficient_role(
    make_client,  # noqa: ANN001
    roles: tuple[str, ...],
    visibility: str,
    collaborators: dict[UUID, str],
) -> None:
    client = make_client(claims=_claims(*roles), note=_note(visibility, collaborators))
    r = _put(client)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "insufficient_role"
    assert r.json()["required"] == "edit"
    assert client.appended == []


def test_draft_as_workspace_viewer_is_refused_before_the_note_is_read(make_client) -> None:  # noqa: ANN001
    """B-8 took `note.write` from `viewer`, so the permission check answers 403 first
    (`deny:`), not `insufficient_role`; either way nothing is written."""
    client = make_client(claims=_claims("viewer"), note=_note("workspace", {}))
    r = _put(client)
    assert r.status_code == 403
    assert "deny:" in r.text
    assert client.appended == []


def test_draft_on_a_note_you_cannot_see_is_404(make_client) -> None:  # noqa: ANN001
    client = make_client(claims=_claims("guest"), note=_note("workspace", {}))
    assert _put(client).status_code == 404
    client = make_client(claims=_claims("member"), note=_note("private", {}))
    assert _put(client).status_code == 404


@pytest.mark.parametrize(
    ("roles", "visibility", "collaborators"),
    [
        (("member",), "workspace", {}),  # workspace member → edit
        (("member",), "private", {CALLER: "edit"}),  # edit collaborator
        (("guest",), "private", {CALLER: "edit"}),  # guest with an edit grant
        (("member",), "workspace", {CALLER: "view"}),  # max(view, workspace edit)
    ],
)
def test_draft_with_edit_is_200(
    make_client,  # noqa: ANN001
    roles: tuple[str, ...],
    visibility: str,
    collaborators: dict[UUID, str],
) -> None:
    client = make_client(claims=_claims(*roles), note=_note(visibility, collaborators))
    r = _put(client)
    assert r.status_code == 200, r.text
    assert r.json()["version_number"] == 2
    (call,) = client.appended
    assert call["created_by"] == CALLER
