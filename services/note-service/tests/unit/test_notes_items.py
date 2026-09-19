"""Author-side action items and responses (Sprint 20).

Items are a projection: the only thing the author changes here is
status. What is worth pinning is the aggregation the clients render
(counts + the comment as text), the 404 for an item of an older
version, the clear, and that an outsider sees nothing.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_models import NoteStatus
from note_service.domain import action_items
from note_service.domain import action_items_repository as items_repo
from note_service.domain import notes_repository as repo

USER = UUID("11111111-1111-1111-1111-111111111111")
OTHER = UUID("12121212-1212-1212-1212-121212121212")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
VERSION = UUID("55555555-5555-5555-5555-555555555555")
LINK = UUID("66666666-6666-6666-6666-666666666666")
ITEM = UUID("77777777-7777-7777-7777-777777777777")
RESP = UUID("88888888-8888-8888-8888-888888888888")
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _claims(sub: UUID = USER) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=["member"],
        sid="s",
        iss="i",
        aud="a",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note() -> repo.NoteRow:
    return repo.NoteRow(
        id=NOTE,
        tenant_id=TENANT,
        code="N-2026-0001",
        status=NoteStatus.FINALIZED,
        current_version_id=VERSION,
        current_version_number=2,
        primary_author_id=USER,
        co_author_ids=[],
        title="Kickoff",
        created_at=NOW,
        updated_at=NOW,
        finalized_at=NOW,
        cancelled_at=None,
        visibility="private",
        shared_with_ids=[],
    )


def _item(**over) -> items_repo.ItemRow:  # noqa: ANN003
    base: dict = {
        "id": ITEM,
        "note_id": NOTE,
        "note_version_id": VERSION,
        "item_key": "k1",
        "position": 0,
        "text": "send the pricing proposal",
        "owner_label": "Anna",
        "owner_confidence": 1.0,
        "due_date": None,
        "due_text": "18 Sep",
        "due_confidence": 1.0,
        "status": "open",
    }
    base.update(over)
    return items_repo.ItemRow(**base)


def _resp(**over) -> items_repo.ResponseRow:  # noqa: ANN003
    base: dict = {
        "id": RESP,
        "note_id": NOTE,
        "link_id": LINK,
        "link_label": "Tom @ Client",
        "kind": "dispute",
        "item_key": "k1",
        "section_key": None,
        "comment": "<b>It was Friday</b>",
        "created_at": NOW,
        "cleared_at": None,
    }
    base.update(over)
    return items_repo.ResponseRow(**base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_items as router_mod

    audit: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _conn)

    world = {
        "note": _note(),
        "items": [_item(), _item(id=uuid4(), item_key="k2", position=1, text="share brand assets")],
        "responses": [_resp(), _resp(id=uuid4(), kind="confirm", item_key="k2", comment=None)],
    }

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return world["note"] if note_id == NOTE else None

    async def _fetch_items(conn, *, version_id):  # noqa: ANN001
        return [i for i in world["items"] if i.note_version_id == version_id]

    async def _fetch_item(conn, *, note_id, item_id):  # noqa: ANN001
        return next((i for i in world["items"] if i.id == item_id), None)

    async def _set_status(conn, *, item_id, status, actor_sub):  # noqa: ANN001
        for i in world["items"]:
            if i.id == item_id:
                i.status = status

    async def _list_responses(conn, *, note_id, include_cleared=False):  # noqa: ANN001
        return [r for r in world["responses"] if include_cleared or r.cleared_at is None]

    async def _clear(conn, *, note_id, response_id, actor_sub):  # noqa: ANN001
        for r in world["responses"]:
            if r.id == response_id and r.cleared_at is None:
                r.cleared_at = NOW
                return r
        return None

    for name, fn in {
        "fetch_items": _fetch_items,
        "fetch_item": _fetch_item,
        "set_item_status": _set_status,
        "list_responses": _list_responses,
        "clear_response": _clear,
    }.items():
        monkeypatch.setattr(items_repo, name, fn)
    monkeypatch.setattr(repo, "fetch_note", _fetch_note)

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return SimpleNamespace(id=version_id)

    async def _ensure_items(conn, *, note, version):  # noqa: ANN001
        return await _fetch_items(conn, version_id=version.id)

    monkeypatch.setattr(repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(action_items, "ensure_items", _ensure_items)

    app = create_app()
    app.dependency_overrides[deps.current_user] = lambda: _claims()
    c = TestClient(app)
    c.world = world  # type: ignore[attr-defined]
    c.audit = audit  # type: ignore[attr-defined]
    c.app_ = app  # type: ignore[attr-defined]
    return c


def test_items_carry_counts_and_the_comment_as_text(client: TestClient) -> None:
    items = client.get(f"/v1/notes/{NOTE}/items").json()
    assert [i["item_key"] for i in items] == ["k1", "k2"]
    assert items[0]["counts"] == {"confirms": 0, "dones": 0, "disputes": 1}
    assert items[0]["responses"][0]["comment"] == "<b>It was Friday</b>"
    assert items[0]["responses"][0]["link_label"] == "Tom @ Client"
    assert items[1]["counts"] == {"confirms": 1, "dones": 0, "disputes": 0}
    assert items[0]["owner_label"] == "Anna"


def test_author_marks_an_item_done(client: TestClient) -> None:
    r = client.patch(f"/v1/notes/{NOTE}/items/{ITEM}", json={"status": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    changed = [a for a in client.audit if a["kind"] == "note.item_status_changed"]
    assert changed[0]["payload"] == {"item_key": "k1", "from": "open", "to": "done"}
    # Same status again: no second audit row.
    client.patch(f"/v1/notes/{NOTE}/items/{ITEM}", json={"status": "done"})
    assert len([a for a in client.audit if a["kind"] == "note.item_status_changed"]) == 1


def test_item_of_an_older_version_is_404(client: TestClient) -> None:
    client.world["items"][0].note_version_id = uuid4()
    assert (
        client.patch(f"/v1/notes/{NOTE}/items/{ITEM}", json={"status": "done"}).status_code == 404
    )


def test_clearing_a_response_hides_it(client: TestClient) -> None:
    r = client.post(f"/v1/notes/{NOTE}/responses/{RESP}/clear")
    assert r.status_code == 200
    assert r.json()["cleared_at"] is not None
    assert client.get(f"/v1/notes/{NOTE}/items").json()[0]["counts"]["disputes"] == 0
    assert client.get(f"/v1/notes/{NOTE}/responses").json() == [
        {**r_, "cleared_at": None} for r_ in client.get(f"/v1/notes/{NOTE}/responses").json()
    ]
    assert (
        len(client.get(f"/v1/notes/{NOTE}/responses", params={"include_cleared": "true"}).json())
        == 2
    )
    assert client.post(f"/v1/notes/{NOTE}/responses/{RESP}/clear").status_code == 404
    assert [a["payload"] for a in client.audit if a["kind"] == "note.response_cleared"] == [
        {"kind": "dispute"}
    ]


def test_outsider_sees_nothing(client: TestClient) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(sub=OTHER)
    assert client.get(f"/v1/notes/{NOTE}/items").status_code == 404
    assert client.get(f"/v1/notes/{NOTE}/responses").status_code == 404
    assert (
        client.patch(f"/v1/notes/{NOTE}/items/{ITEM}", json={"status": "done"}).status_code == 404
    )
    assert client.post(f"/v1/notes/{NOTE}/responses/{RESP}/clear").status_code == 404


def test_audit_payloads_never_carry_the_comment(client: TestClient) -> None:
    client.patch(f"/v1/notes/{NOTE}/items/{ITEM}", json={"status": "dropped"})
    client.post(f"/v1/notes/{NOTE}/responses/{RESP}/clear")
    assert "Friday" not in repr(client.audit)
