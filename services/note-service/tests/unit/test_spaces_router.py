"""/v1/spaces routes with the DB stubbed (0021).

Mirrors ``test_calendar_router``: the real handlers run against an
overridden auth dependency and monkeypatched repository functions.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import spaces_repository as repo

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
SPACE = UUID("33333333-3333-3333-3333-333333333333")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _claims() -> Claims:
    return Claims(
        sub=USER,
        tid=TENANT,
        roles=["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _space(**over) -> repo.SpaceRow:  # noqa: ANN003
    base: dict = {
        "id": SPACE,
        "tenant_id": TENANT,
        "user_sub": USER,
        "name": "Clients",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(over)
    return repo.SpaceRow(**base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import spaces as router_mod

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    spaces: list[repo.SpaceRow] = []
    items: dict[UUID, UUID] = {}
    calls: list[tuple[str, dict]] = []

    async def _list_spaces(conn, *, user_sub):  # noqa: ANN001
        return [s for s in spaces if s.user_sub == user_sub]

    async def _list_items(conn, *, user_sub):  # noqa: ANN001
        return dict(items)

    async def _create(conn, *, tenant_id, user_sub, name):  # noqa: ANN001
        calls.append(("create", {"name": name}))
        row = _space(id=uuid4(), name=name)
        spaces.append(row)
        return row

    async def _rename(conn, *, user_sub, space_id, name):  # noqa: ANN001
        calls.append(("rename", {"space_id": space_id, "name": name}))
        for i, s in enumerate(spaces):
            if s.id == space_id and s.user_sub == user_sub:
                spaces[i] = _space(id=space_id, name=name)
                return spaces[i]
        return None

    async def _delete(conn, *, user_sub, space_id):  # noqa: ANN001
        calls.append(("delete", {"space_id": space_id}))
        before = len(spaces)
        spaces[:] = [s for s in spaces if not (s.id == space_id and s.user_sub == user_sub)]
        return len(spaces) < before

    async def _file(conn, *, tenant_id, user_sub, note_id, space_id):  # noqa: ANN001
        calls.append(("file", {"note_id": note_id, "space_id": space_id}))
        if space_id is not None and not any(s.id == space_id for s in spaces):
            return False
        if space_id is None:
            items.pop(note_id, None)
        else:
            items[note_id] = space_id
        return True

    for name, fn in {
        "list_spaces": _list_spaces,
        "list_items": _list_items,
        "create_space": _create,
        "rename_space": _rename,
        "delete_space": _delete,
        "set_note_space": _file,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    c = TestClient(app)
    c.spaces = spaces  # type: ignore[attr-defined]
    c.items = items  # type: ignore[attr-defined]
    c.calls = calls  # type: ignore[attr-defined]
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    return c


def test_list_groups_notes_under_their_space(client: TestClient) -> None:
    client.spaces.append(_space())
    client.items[NOTE] = SPACE
    r = client.get("/v1/spaces")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "spaces": [
            {
                "id": str(SPACE),
                "name": "Clients",
                "created_at": NOW.isoformat(),
                "note_ids": [str(NOTE)],
            }
        ]
    }


def test_create_trims_name_and_audits(client: TestClient) -> None:
    r = client.post("/v1/spaces", json={"name": "  Acme   Corp "})
    assert r.status_code == 201
    assert r.json()["name"] == "Acme Corp"
    assert r.json()["note_ids"] == []
    assert client.calls == [("create", {"name": "Acme Corp"})]
    assert [c["kind"] for c in client.audit_calls] == ["space.created"]
    # Never the name in the audit payload.
    assert "name" not in client.audit_calls[0]["payload"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_create_rejects_bad_names(client: TestClient, name: str) -> None:
    assert client.post("/v1/spaces", json={"name": name}).status_code == 422


def test_rename_returns_the_notes_filed_there(client: TestClient) -> None:
    client.spaces.append(_space())
    client.items[NOTE] = SPACE
    r = client.put(f"/v1/spaces/{SPACE}", json={"name": "Customers"})
    assert r.status_code == 200
    assert r.json()["name"] == "Customers"
    assert r.json()["note_ids"] == [str(NOTE)]
    assert [c["kind"] for c in client.audit_calls] == ["space.renamed"]


def test_rename_and_delete_404_for_a_space_that_is_not_mine(client: TestClient) -> None:
    other = uuid4()
    assert client.put(f"/v1/spaces/{other}", json={"name": "X"}).status_code == 404
    assert client.delete(f"/v1/spaces/{other}").status_code == 404
    assert client.audit_calls == []


def test_delete_stamps_and_audits(client: TestClient) -> None:
    client.spaces.append(_space())
    assert client.delete(f"/v1/spaces/{SPACE}").status_code == 204
    assert client.spaces == []
    assert [c["kind"] for c in client.audit_calls] == ["space.deleted"]
    assert client.audit_calls[0]["target_id"] == SPACE


def test_file_and_unfile_a_note(client: TestClient) -> None:
    client.spaces.append(_space())
    r = client.put(f"/v1/notes/{NOTE}/space", json={"space_id": str(SPACE)})
    assert r.status_code == 204
    assert client.items == {NOTE: SPACE}
    r = client.put(f"/v1/notes/{NOTE}/space", json={"space_id": None})
    assert r.status_code == 204
    assert client.items == {}
    # Filing is not an audited act.
    assert client.audit_calls == []


def test_file_into_someone_elses_space_404s(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/space", json={"space_id": str(uuid4())})
    assert r.status_code == 404
    assert client.items == {}


def test_file_body_must_carry_space_id(client: TestClient) -> None:
    assert client.put(f"/v1/notes/{NOTE}/space", json={}).status_code == 422
