"""W3 Sharing API v2 (B-2): roles per person, not_a_member → invite, transcript toggle,
no workspace visibility in a personal workspace. Real handlers, DB stubbed."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import action_items_repository as items_repo
from note_service.domain import notes_repository as repo
from note_service.domain import sharing_policy

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("33333333-3333-3333-3333-333333333333")
COLLEAGUE = UUID("44444444-4444-4444-4444-444444444444")
CO = UUID("55555555-5555-5555-5555-555555555555")
GUEST = UUID("66666666-6666-6666-6666-666666666666")
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _claims(sub: UUID = USER, *roles: str) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=list(roles) or ["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note(**over) -> repo.NoteRow:  # noqa: ANN003
    base: dict = {
        "id": NOTE,
        "tenant_id": TENANT,
        "code": "N-2026-0001",
        "status": repo.NoteStatus.DRAFT,
        "current_version_id": uuid4(),
        "current_version_number": 1,
        "primary_author_id": USER,
        "co_author_ids": [CO],
        "title": "Acme kickoff",
        "created_at": NOW,
        "updated_at": NOW,
        "finalized_at": None,
        "cancelled_at": None,
        "visibility": "private",
    }
    base.update(over)
    return repo.NoteRow(**base)


PEOPLE = {
    USER: ("anna@acme.com", "Anna Koval", "owner"),
    CO: ("co@acme.com", "Co Author", "member"),
    COLLEAGUE: ("colleague@acme.com", "Colleague", "member"),
    GUEST: ("guest@client.com", "Guest", "guest"),
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_sharing as router_mod

    audit_calls: list[dict] = []
    notified: list[dict] = []
    access_changed: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            redis=object(),
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    async def _emit(*args, **kwargs):  # noqa: ANN002, ANN003
        notified.append(kwargs)

    async def _emit_changed(*args, **kwargs):  # noqa: ANN002, ANN003
        access_changed.append(kwargs)

    monkeypatch.setattr(router_mod, "emit_note_event", _emit)
    monkeypatch.setattr(router_mod, "emit_note_access_changed", _emit_changed)

    state: dict = {"note": _note(), "kind": "team", "pending_reads": 0}

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return state["note"] if note_id == NOTE else None

    async def _find_member(conn, *, email):  # noqa: ANN001
        for sub, (address, name, _role) in PEOPLE.items():
            if address == email.lower():
                return SimpleNamespace(sub=sub, email=address, display_name=name)
        return None

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        return [
            SimpleNamespace(sub=s, email=PEOPLE[s][0], display_name=PEOPLE[s][1])
            for s in subs
            if s in PEOPLE
        ]

    async def _membership_roles(conn, *, subs):  # noqa: ANN001
        return {s: PEOPLE[s][2] for s in subs if s in PEOPLE}

    async def _upsert(conn, *, note_id, tenant_id, user_sub, role, granted_by):  # noqa: ANN001
        note = state["note"]
        previous = note.collaborators.get(user_sub)
        state["note"] = _note(
            visibility=note.visibility,
            transcript_shared=note.transcript_shared,
            collaborators={**note.collaborators, user_sub: role},
        )
        return previous

    async def _remove(conn, *, note_id, user_sub):  # noqa: ANN001
        note = state["note"]
        if user_sub not in note.collaborators:
            return False
        rest = {s: r for s, r in note.collaborators.items() if s != user_sub}
        state["note"] = _note(
            visibility=note.visibility,
            transcript_shared=note.transcript_shared,
            collaborators=rest,
        )
        return True

    async def _set_transcript(conn, *, note_id, shared):  # noqa: ANN001
        note = state["note"]
        state["note"] = _note(
            visibility=note.visibility, transcript_shared=shared, collaborators=note.collaborators
        )

    async def _set_visibility(conn, *, note_id, visibility):  # noqa: ANN001
        note = state["note"]
        state["note"] = _note(
            visibility=visibility,
            transcript_shared=note.transcript_shared,
            collaborators=note.collaborators,
        )

    async def _no_links(conn, *, note_id):  # noqa: ANN001
        return []

    for name, fn in {
        "fetch_note": _fetch_note,
        "find_member_by_email": _find_member,
        "fetch_members": _fetch_members,
        "membership_roles": _membership_roles,
        "upsert_collaborator": _upsert,
        "remove_collaborator": _remove,
        "set_transcript_shared": _set_transcript,
        "set_visibility": _set_visibility,
        "list_live_share_links": _no_links,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    async def _no_counts(conn, *, note_id):  # noqa: ANN001
        return {}

    monkeypatch.setattr(items_repo, "live_response_counts_by_link", _no_counts)

    async def _load_policy(conn, *, tenant_id):  # noqa: ANN001
        return sharing_policy.SharingPolicy(), "free"

    async def _tenant_kind(conn, *, tenant_id):  # noqa: ANN001
        return state["kind"]

    monkeypatch.setattr(sharing_policy, "load_policy", _load_policy)
    monkeypatch.setattr(sharing_policy, "tenant_kind", _tenant_kind)

    async def _pending(conn, note_id):  # noqa: ANN001
        state["pending_reads"] += 1
        return [
            router_mod.PendingNoteInvite(
                invitation_id=uuid4(),
                email_masked="g***t@client.com",
                note_role="comment",
                expires_at=NOW.isoformat(),
            )
        ]

    monkeypatch.setattr(router_mod, "_pending", _pending)

    app = create_app()
    app.dependency_overrides[deps.current_user] = lambda: _claims()
    c = TestClient(app)
    c.app_ = app  # type: ignore[attr-defined]
    c.state_ = state  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.notified = notified  # type: ignore[attr-defined]
    c.access_changed = access_changed  # type: ignore[attr-defined]
    return c


def _as(client: TestClient, claims: Claims) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: claims  # type: ignore[attr-defined]


def _kinds(client: TestClient) -> list[str]:
    return [c["kind"] for c in client.audit]  # type: ignore[attr-defined]


# ── GET /sharing ────────────────────────────────────────────────────


def test_sharing_view_lists_people_with_level_and_source(client: TestClient) -> None:
    client.state_["note"] = _note(collaborators={GUEST: "comment"})  # type: ignore[attr-defined]
    body = client.get(f"/v1/notes/{NOTE}/sharing").json()
    assert body["my_level"] == "manage"
    assert body["workspace_kind"] == "team"
    assert body["transcript_shared"] is False
    people = {p["sub"]: p for p in body["people"]}
    assert people[str(USER)]["source"] == "author"
    assert people[str(USER)]["level"] == "manage"
    assert people[str(USER)]["can_change"] is False
    assert people[str(CO)]["source"] == "author"
    assert people[str(GUEST)] == {
        "sub": str(GUEST),
        "email": "guest@client.com",
        "display_name": "Guest",
        "level": "comment",
        "source": "collaborator",
        "membership_role": "guest",
        "can_change": True,
    }
    # The deprecated list is the collaborators only.
    assert [m["sub"] for m in body["shared_with"]] == [str(GUEST)]
    assert len(body["pending"]) == 1


def test_pending_invitations_are_for_managers_only(client: TestClient) -> None:
    client.state_["note"] = _note(collaborators={COLLEAGUE: "view"})  # type: ignore[attr-defined]
    _as(client, _claims(COLLEAGUE))
    body = client.get(f"/v1/notes/{NOTE}/sharing").json()
    assert body["my_level"] == "view"
    assert body["can_manage"] is False
    assert body["pending"] == []
    assert client.state_["pending_reads"] == 0  # type: ignore[attr-defined]
    assert all(p["can_change"] is False for p in body["people"])


# ── PUT/DELETE /collaborators/{sub} ─────────────────────────────────


def test_collaborator_role_is_upserted(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/collaborators/{COLLEAGUE}", json={"role": "view"})
    assert r.status_code == 200, r.text
    assert client.state_["note"].collaborators == {COLLEAGUE: "view"}  # type: ignore[attr-defined]
    # A new grant pings the person with their role.
    (ping,) = client.notified  # type: ignore[attr-defined]
    assert ping["primary_author_id"] == COLLEAGUE
    assert ping["extra_payload"]["role"] == "view"

    r = client.put(f"/v1/notes/{NOTE}/collaborators/{COLLEAGUE}", json={"role": "edit"})
    assert r.status_code == 200
    assert client.state_["note"].collaborators == {COLLEAGUE: "edit"}  # type: ignore[attr-defined]
    level = {p["sub"]: p["level"] for p in r.json()["people"]}
    assert level[str(COLLEAGUE)] == "edit"
    # A change is an access_changed, not a second "shared with you".
    assert len(client.notified) == 1  # type: ignore[attr-defined]
    (changed,) = client.access_changed  # type: ignore[attr-defined]
    assert changed["user_sub"] == COLLEAGUE
    assert changed["role"] == "edit"
    shared = [c["payload"] for c in client.audit if c["kind"] == "note.shared"]  # type: ignore[attr-defined]
    assert shared[-1] == {"with": str(COLLEAGUE), "via": "role_change", "role": "edit"}


def test_an_author_cannot_be_given_a_role(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/collaborators/{CO}", json={"role": "view"})
    assert r.status_code == 409
    assert "is_author" in r.text
    assert client.state_["note"].collaborators == {}  # type: ignore[attr-defined]


def test_a_non_member_cannot_be_given_a_role(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/collaborators/{uuid4()}", json={"role": "view"})
    assert r.status_code == 404
    assert "not_a_member" in r.text
    assert client.state_["note"].collaborators == {}  # type: ignore[attr-defined]


def test_an_unknown_role_is_refused(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/collaborators/{COLLEAGUE}", json={"role": "manage"})
    assert r.status_code == 422


def test_only_a_manager_changes_roles(client: TestClient) -> None:
    client.state_["note"] = _note(collaborators={COLLEAGUE: "edit"})  # type: ignore[attr-defined]
    _as(client, _claims(COLLEAGUE))
    r = client.put(f"/v1/notes/{NOTE}/collaborators/{GUEST}", json={"role": "view"})
    assert r.status_code == 403
    assert "insufficient_role" in r.text
    assert client.state_["note"].collaborators == {COLLEAGUE: "edit"}  # type: ignore[attr-defined]


def test_removing_a_collaborator_revokes_and_tells_them(client: TestClient) -> None:
    client.state_["note"] = _note(collaborators={GUEST: "comment"})  # type: ignore[attr-defined]
    r = client.delete(f"/v1/notes/{NOTE}/collaborators/{GUEST}")
    assert r.status_code == 204
    assert client.state_["note"].collaborators == {}  # type: ignore[attr-defined]
    assert "note.unshared" in _kinds(client)
    (changed,) = client.access_changed  # type: ignore[attr-defined]
    assert changed["user_sub"] == GUEST
    assert changed["role"] is None
    # Removing nobody is quiet.
    client.audit.clear()  # type: ignore[attr-defined]
    assert client.delete(f"/v1/notes/{NOTE}/collaborators/{GUEST}").status_code == 204
    assert client.audit == []  # type: ignore[attr-defined]


# ── POST /share ─────────────────────────────────────────────────────


def test_share_with_a_member_is_201_with_the_role(client: TestClient) -> None:
    r = client.post(
        f"/v1/notes/{NOTE}/share", json={"email": "colleague@acme.com", "role": "comment"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "granted"
    assert client.state_["note"].collaborators == {COLLEAGUE: "comment"}  # type: ignore[attr-defined]
    assert {p["sub"]: p["level"] for p in body["sharing"]["people"]}[str(COLLEAGUE)] == "comment"
    shared = [c["payload"] for c in client.audit if c["kind"] == "note.shared"]  # type: ignore[attr-defined]
    assert shared == [{"with": str(COLLEAGUE), "via": "member", "role": "comment"}]


def test_share_role_defaults_to_edit(client: TestClient) -> None:
    r = client.post(f"/v1/notes/{NOTE}/share", json={"email": "colleague@acme.com"})
    assert r.status_code == 201
    assert client.state_["note"].collaborators == {COLLEAGUE: "edit"}  # type: ignore[attr-defined]


def test_share_with_a_non_member_offers_an_invitation(client: TestClient) -> None:
    r = client.post(f"/v1/notes/{NOTE}/share", json={"email": "outsider@example.com"})
    assert r.status_code == 404
    # A dict detail is lifted into the problem document's top level.
    body = r.json()
    assert body["code"] == "not_a_member"
    assert body["can_invite"] is True
    assert client.state_["note"].collaborators == {}  # type: ignore[attr-defined]
    assert client.notified == []  # type: ignore[attr-defined]


# ── PUT /transcript-sharing ─────────────────────────────────────────


def test_transcript_toggle_is_audited_once_per_change(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/transcript-sharing", json={"shared": True})
    assert r.status_code == 200
    assert r.json()["transcript_shared"] is True
    assert client.state_["note"].transcript_shared is True  # type: ignore[attr-defined]
    events = [c for c in client.audit if c["kind"] == "note.transcript_sharing_changed"]  # type: ignore[attr-defined]
    assert [e["payload"] for e in events] == [{"shared": True}]
    # Same value again: no change, no audit.
    assert (
        client.put(f"/v1/notes/{NOTE}/transcript-sharing", json={"shared": True}).status_code == 200
    )
    assert _kinds(client).count("note.transcript_sharing_changed") == 1


def test_transcript_toggle_needs_manage(client: TestClient) -> None:
    client.state_["note"] = _note(collaborators={COLLEAGUE: "edit"})  # type: ignore[attr-defined]
    _as(client, _claims(COLLEAGUE))
    r = client.put(f"/v1/notes/{NOTE}/transcript-sharing", json={"shared": True})
    assert r.status_code == 403
    assert client.state_["note"].transcript_shared is False  # type: ignore[attr-defined]


# ── PUT /visibility ─────────────────────────────────────────────────


def test_workspace_visibility_is_refused_in_a_personal_workspace(client: TestClient) -> None:
    client.state_["kind"] = "personal"  # type: ignore[attr-defined]
    r = client.put(f"/v1/notes/{NOTE}/visibility", json={"visibility": "workspace"})
    assert r.status_code == 409
    assert "personal_workspace" in r.text
    assert client.state_["note"].visibility == "private"  # type: ignore[attr-defined]
    assert "note.visibility_changed" not in _kinds(client)
    # Private is always fine.
    assert (
        client.put(f"/v1/notes/{NOTE}/visibility", json={"visibility": "private"}).status_code
        == 200
    )


def test_workspace_visibility_in_a_team_workspace(client: TestClient) -> None:
    r = client.put(f"/v1/notes/{NOTE}/visibility", json={"visibility": "workspace"})
    assert r.status_code == 200
    assert r.json()["visibility"] == "workspace"
    assert "note.visibility_changed" in _kinds(client)
