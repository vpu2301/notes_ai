"""Comments on a note (W3 B-4) with the DB and Redis stubbed: who may post,
resolve and delete per level, IDOR on the comment id, anchors, the limiter,
and the debounced, content-free notification.
"""

from __future__ import annotations

import contextlib
import itertools
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import action_items
from note_service.domain import comments_repository as comments_repo
from note_service.domain import notes_repository as repo

TENANT = UUID("22222222-2222-2222-2222-222222222222")
AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
VIEWER = UUID("33333333-3333-3333-3333-333333333331")
COMMENTER = UUID("33333333-3333-3333-3333-333333333332")
EDITOR = UUID("33333333-3333-3333-3333-333333333333")
GUEST = UUID("33333333-3333-3333-3333-333333333334")
WS_VIEWER = UUID("33333333-3333-3333-3333-333333333335")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
WS_NOTE = UUID("44444444-4444-4444-4444-444444444445")
OTHER_NOTE = UUID("44444444-4444-4444-4444-444444444446")
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

NAMES = {
    AUTHOR: "Anna Koval",
    VIEWER: "Vic Viewer",
    COMMENTER: "Cora Commenter",
    EDITOR: "Ed Editor",
    GUEST: "Gus Guest",
    WS_VIEWER: "Wes Viewer",
}


def _claims(sub: UUID, roles: list[str]) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=roles,
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


PERSONAS = {
    "author": _claims(AUTHOR, ["member"]),
    "view": _claims(VIEWER, ["member"]),
    "comment": _claims(COMMENTER, ["member"]),
    "edit": _claims(EDITOR, ["member"]),
    "guest": _claims(GUEST, ["guest"]),
    "ws_viewer": _claims(WS_VIEWER, ["viewer"]),
}


def _note(note_id: UUID, **over) -> repo.NoteRow:  # noqa: ANN003
    base: dict = {
        "id": note_id,
        "tenant_id": TENANT,
        "code": "N-2026-0001",
        "status": repo.NoteStatus.DRAFT,
        "current_version_id": uuid4(),
        "current_version_number": 1,
        "primary_author_id": AUTHOR,
        "co_author_ids": [],
        "title": "Acme kickoff",
        "created_at": NOW,
        "updated_at": NOW,
        "finalized_at": None,
        "cancelled_at": None,
        "visibility": "private",
        "collaborators": {VIEWER: "view", COMMENTER: "comment", EDITOR: "edit", GUEST: "view"},
    }
    base.update(over)
    return repo.NoteRow(**base)


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.kv[key] = self.kv.get(key, 0) + 1
        return self.kv[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_comments as router_mod

    audit_calls: list[dict] = []
    notified: list[dict] = []
    redis = _FakeRedis()

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            redis=redis,
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    async def _emit(redis, **kwargs):  # noqa: ANN001, ANN003
        notified.append(kwargs)
        return []

    monkeypatch.setattr(router_mod, "emit_note_commented", _emit)

    notes = {
        NOTE: _note(NOTE),
        WS_NOTE: _note(WS_NOTE, visibility="workspace", collaborators={}),
        OTHER_NOTE: _note(OTHER_NOTE),
    }

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return notes.get(note_id)

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        return [
            SimpleNamespace(sub=s, email="x@acme.com", display_name=NAMES[s])
            for s in subs
            if s in NAMES
        ]

    async def _membership_roles(conn, *, subs):  # noqa: ANN001
        return {s: ("viewer" if s == WS_VIEWER else "member") for s in subs}

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return SimpleNamespace(
            id=version_id,
            content=SimpleNamespace(sections=[SimpleNamespace(section_key="decisions")]),
        )

    async def _ensure_items(conn, *, note, version):  # noqa: ANN001
        return [SimpleNamespace(item_key="k1")]

    monkeypatch.setattr(repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(repo, "fetch_members", _fetch_members)
    monkeypatch.setattr(repo, "membership_roles", _membership_roles)
    monkeypatch.setattr(repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(action_items, "ensure_items", _ensure_items)

    rows: dict[UUID, comments_repo.CommentRow] = {}
    deleted: set[UUID] = set()
    clock = itertools.count()

    def _live(note_id: UUID, comment_id: UUID) -> comments_repo.CommentRow | None:
        row = rows.get(comment_id)
        if row is None or row.note_id != note_id or comment_id in deleted:
            return None
        return row

    async def _insert(conn, *, tenant_id, note_id, author_sub, anchor_kind, anchor_key, body):  # noqa: ANN001
        row = comments_repo.CommentRow(
            id=uuid4(),
            note_id=note_id,
            tenant_id=tenant_id,
            author_sub=author_sub,
            anchor_kind=anchor_kind,
            anchor_key=anchor_key,
            body=body,
            created_at=NOW.replace(second=next(clock) % 60),
            edited_at=None,
            resolved_at=None,
            resolved_by=None,
        )
        rows[row.id] = row
        return row

    async def _list(conn, *, note_id):  # noqa: ANN001
        return [r for r in rows.values() if r.note_id == note_id and r.id not in deleted]

    async def _fetch(conn, *, note_id, comment_id):  # noqa: ANN001
        return _live(note_id, comment_id)

    async def _update(conn, *, note_id, comment_id, body):  # noqa: ANN001
        row = _live(note_id, comment_id)
        if row is None:
            return None
        rows[comment_id] = comments_repo.CommentRow(
            **{**_fields(row), "body": body, "edited_at": NOW}
        )
        return rows[comment_id]

    async def _resolve(conn, *, note_id, comment_id, resolved_by):  # noqa: ANN001
        row = _live(note_id, comment_id)
        if row is None:
            return None
        rows[comment_id] = comments_repo.CommentRow(
            **{
                **_fields(row),
                "resolved_by": resolved_by,
                "resolved_at": NOW if resolved_by else None,
            }
        )
        return rows[comment_id]

    async def _delete(conn, *, note_id, comment_id, deleted_by):  # noqa: ANN001
        if _live(note_id, comment_id) is None:
            return False
        deleted.add(comment_id)
        return True

    async def _commenters(conn, *, note_id, anchor_kind, anchor_key):  # noqa: ANN001
        return list(
            {
                r.author_sub
                for r in rows.values()
                if r.note_id == note_id
                and r.anchor_kind == anchor_kind
                and r.anchor_key == anchor_key
                and r.id not in deleted
            }
        )

    for name, fn in {
        "insert_comment": _insert,
        "list_comments": _list,
        "fetch_comment": _fetch,
        "update_body": _update,
        "set_resolved": _resolve,
        "soft_delete": _delete,
        "commenters_on_anchor": _commenters,
    }.items():
        monkeypatch.setattr(comments_repo, name, fn)

    app = create_app()
    who = {"claims": PERSONAS["author"]}
    app.dependency_overrides[deps.current_user] = lambda: who["claims"]
    c = TestClient(app)
    c.who = who  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.notified = notified  # type: ignore[attr-defined]
    c.rows = rows  # type: ignore[attr-defined]
    c.deleted = deleted  # type: ignore[attr-defined]
    c.redis = redis  # type: ignore[attr-defined]
    return c


def _fields(row: comments_repo.CommentRow) -> dict:
    return {name: getattr(row, name) for name in comments_repo.CommentRow.__slots__}


def _as(client: TestClient, persona: str) -> TestClient:
    client.who["claims"] = PERSONAS[persona]  # type: ignore[attr-defined]
    return client


def _post(client: TestClient, note_id: UUID = NOTE, **body) -> object:  # noqa: ANN003
    body.setdefault("body", "Looks right to me")
    return client.post(f"/v1/notes/{note_id}/comments", json=body)


def _add(client: TestClient, persona: str, note_id: UUID = NOTE, **body) -> str:  # noqa: ANN003
    r = _post(_as(client, persona), note_id, **body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── Who may post ────────────────────────────────────────────────────


def test_view_collaborator_cannot_comment(client: TestClient) -> None:
    r = _post(_as(client, "view"))
    assert r.status_code == 403
    assert r.json()["code"] == "insufficient_role"
    assert r.json()["required"] == "comment"
    assert client.rows == {}  # type: ignore[attr-defined]


def test_comment_collaborator_posts_and_is_audited_without_the_body(client: TestClient) -> None:
    r = _post(_as(client, "comment"), anchor_kind="section", anchor_key="decisions")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["author"] == {"sub": str(COMMENTER), "display_name": "Cora Commenter"}
    assert body["anchor_kind"] == "section"
    assert body["anchor_present"] is True
    assert body["can_edit"] is True
    assert body["can_resolve"] is False
    assert body["can_delete"] is True

    (audit,) = client.audit  # type: ignore[attr-defined]
    assert audit["kind"] == "note.commented"
    assert audit["payload"] == {"anchor_kind": "section"}
    assert "Looks right" not in str(audit)

    (note_event,) = client.notified  # type: ignore[attr-defined]
    assert note_event["anchor_kind"] == "section"
    assert AUTHOR in note_event["recipients"]
    assert note_event["actor_user_id"] == COMMENTER


def test_workspace_viewer_comments_on_a_workspace_note(client: TestClient) -> None:
    assert _post(_as(client, "ws_viewer"), WS_NOTE).status_code == 201


def test_workspace_viewer_cannot_see_a_private_note(client: TestClient) -> None:
    assert _post(_as(client, "ws_viewer"), NOTE).status_code == 404


def test_guest_with_view_cannot_comment(client: TestClient) -> None:
    r = _post(_as(client, "guest"))
    assert r.status_code == 403
    assert r.json()["code"] == "insufficient_role"


def test_guest_cannot_see_a_workspace_note(client: TestClient) -> None:
    assert _post(_as(client, "guest"), WS_NOTE).status_code == 404


def test_html_is_text_and_links_are_allowed(client: TestClient) -> None:
    r = _post(_as(client, "edit"), body="  see https://acme.com <b>now</b>\x07 ")
    assert r.status_code == 201
    assert r.json()["body"] == "see https://acme.com <b>now</b>"


@pytest.mark.parametrize("text", ["   ", "x" * 2001])
def test_empty_or_long_bodies_are_refused(client: TestClient, text: str) -> None:
    assert _post(_as(client, "edit"), body=text).status_code == 422


def test_unknown_anchor_is_404(client: TestClient) -> None:
    r = _post(_as(client, "edit"), anchor_kind="item", anchor_key="gone")
    assert r.status_code == 404


def test_other_commenters_on_the_anchor_are_told(client: TestClient) -> None:
    _add(client, "comment", anchor_kind="item", anchor_key="k1")
    _add(client, "edit", anchor_kind="item", anchor_key="k1")
    last = client.notified[-1]  # type: ignore[attr-defined]
    assert COMMENTER in last["recipients"]
    assert AUTHOR in last["recipients"]


def test_rate_limit_is_120_an_hour(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.routers import notes_comments as router_mod

    monkeypatch.setattr(router_mod, "COMMENTS_PER_HOUR", 2)
    _as(client, "edit")
    assert _post(client).status_code == 201
    assert _post(client).status_code == 201
    r = _post(client)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_rate_limit_fails_open_without_redis(client: TestClient) -> None:
    class _Down:
        async def incr(self, key: str) -> int:
            raise ConnectionError("down")

    from note_service import deps

    deps.get_state().redis = _Down()  # type: ignore[attr-defined]
    assert _post(_as(client, "edit")).status_code == 201


# ── List ────────────────────────────────────────────────────────────


def test_list_marks_removed_anchors_and_per_caller_flags(client: TestClient) -> None:
    cid = _add(client, "comment", anchor_kind="section", anchor_key="decisions")
    # A section that a regeneration removed.
    stale = _add(client, "edit")
    client.rows[UUID(stale)] = comments_repo.CommentRow(  # type: ignore[attr-defined]
        **{
            **_fields(client.rows[UUID(stale)]),  # type: ignore[attr-defined]
            "anchor_kind": "section",
            "anchor_key": "old",
        }
    )

    r = _as(client, "view").get(f"/v1/notes/{NOTE}/comments")
    assert r.status_code == 200
    items = {i["id"]: i for i in r.json()["items"]}
    assert items[cid]["anchor_present"] is True
    assert items[stale]["anchor_present"] is False
    for item in items.values():
        assert item["can_edit"] is False
        assert item["can_resolve"] is False
        assert item["can_delete"] is False

    mine = _as(client, "comment").get(f"/v1/notes/{NOTE}/comments").json()["items"]
    assert next(i for i in mine if i["id"] == cid)["can_edit"] is True

    owner = _as(client, "author").get(f"/v1/notes/{NOTE}/comments").json()["items"]
    assert all(i["can_delete"] and i["can_resolve"] for i in owner)


def test_list_is_404_for_someone_who_cannot_see_the_note(client: TestClient) -> None:
    assert _as(client, "ws_viewer").get(f"/v1/notes/{NOTE}/comments").status_code == 404


# ── Edit, resolve, delete ───────────────────────────────────────────


def test_only_the_author_edits_a_comment(client: TestClient) -> None:
    cid = _add(client, "comment")
    r = _as(client, "edit").patch(f"/v1/notes/{NOTE}/comments/{cid}", json={"body": "Mine now"})
    assert r.status_code == 403
    r = _as(client, "comment").patch(f"/v1/notes/{NOTE}/comments/{cid}", json={"body": "Fixed"})
    assert r.status_code == 200
    assert r.json()["body"] == "Fixed"
    assert r.json()["edited_at"] is not None


def test_resolve_needs_edit(client: TestClient) -> None:
    cid = _add(client, "comment")
    r = _as(client, "comment").post(f"/v1/notes/{NOTE}/comments/{cid}/resolve")
    assert r.status_code == 403
    assert r.json()["required"] == "edit"

    r = _as(client, "edit").post(f"/v1/notes/{NOTE}/comments/{cid}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved_at"] is not None
    assert r.json()["resolved_by_display"] == "Ed Editor"

    r = _as(client, "edit").post(f"/v1/notes/{NOTE}/comments/{cid}/unresolve")
    assert r.status_code == 200
    assert r.json()["resolved_at"] is None
    assert r.json()["resolved_by_display"] is None


def test_delete_by_author_or_manager_only(client: TestClient) -> None:
    first = _add(client, "comment")
    second = _add(client, "comment")

    # An editor is not a manager and not the author.
    assert _as(client, "edit").delete(f"/v1/notes/{NOTE}/comments/{first}").status_code == 403
    assert _as(client, "comment").delete(f"/v1/notes/{NOTE}/comments/{first}").status_code == 204
    assert UUID(first) in client.deleted  # type: ignore[attr-defined]
    # The note's author manages it.
    assert _as(client, "author").delete(f"/v1/notes/{NOTE}/comments/{second}").status_code == 204
    # Gone is gone.
    assert _as(client, "author").delete(f"/v1/notes/{NOTE}/comments/{second}").status_code == 404


def test_a_comment_id_from_another_note_is_404(client: TestClient) -> None:
    foreign = _add(client, "author", OTHER_NOTE)
    _as(client, "author")
    assert (
        client.patch(f"/v1/notes/{NOTE}/comments/{foreign}", json={"body": "x"}).status_code == 404
    )
    assert client.post(f"/v1/notes/{NOTE}/comments/{foreign}/resolve").status_code == 404
    assert client.delete(f"/v1/notes/{NOTE}/comments/{foreign}").status_code == 404
    assert UUID(foreign) not in client.deleted  # type: ignore[attr-defined]


# ── Notification producer ───────────────────────────────────────────


class _DebounceRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key, value, *, nx, ex):  # noqa: ANN001
        if key in self.keys:
            return None
        self.keys.add(key)
        return True


@pytest.mark.asyncio
async def test_comment_notification_is_debounced_per_recipient_and_skips_the_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from note_service import notifications

    published: list = []

    async def _publish(redis, event):  # noqa: ANN001
        published.append(event)

    monkeypatch.setattr(notifications, "publish_event", _publish)
    monkeypatch.setattr(notifications.settings, "notifications_enabled", True)
    redis = _DebounceRedis()

    async def _emit(recipients: list[UUID]) -> list[UUID]:
        return await notifications.emit_note_commented(
            redis,
            tenant_id=TENANT,
            note_id=NOTE,
            note_code="N-2026-0001",
            actor_user_id=COMMENTER,
            recipients=recipients,
            anchor_kind="item",
        )

    assert await _emit([AUTHOR, COMMENTER, AUTHOR]) == [AUTHOR]
    (event,) = published
    assert event.category == "note.commented"
    assert event.recipient_hints == (AUTHOR,)
    assert event.payload == {"note_code": "N-2026-0001", "anchor_kind": "item"}

    # Within the window the author is not told again; a new commenter-recipient is.
    assert await _emit([AUTHOR, EDITOR]) == [EDITOR]
    assert published[-1].recipient_hints == (EDITOR,)
    assert await _emit([AUTHOR]) == []
    assert len(published) == 2


@pytest.mark.asyncio
async def test_access_changed_names_only_the_person_and_the_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from note_service import notifications

    published: list = []

    async def _publish(redis, event):  # noqa: ANN001
        published.append(event)

    monkeypatch.setattr(notifications, "publish_event", _publish)
    monkeypatch.setattr(notifications.settings, "notifications_enabled", True)

    for role in ("comment", None):
        await notifications.emit_note_access_changed(
            object(),
            tenant_id=TENANT,
            note_id=NOTE,
            note_code="N-2026-0001",
            actor_user_id=AUTHOR,
            user_sub=EDITOR,
            role=role,
        )
    changed, revoked = published
    assert changed.category == "note.access_changed"
    assert changed.recipient_hints == (EDITOR,)
    assert changed.payload == {"note_code": "N-2026-0001", "role": "comment"}
    assert revoked.payload == {"note_code": "N-2026-0001"}
