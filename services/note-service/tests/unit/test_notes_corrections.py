"""Corrections and the glossary, at the route level (Sprint 35).

Real handlers, auth overridden, the DB stubbed — the rig shape the other
note-service router tests use.
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
from note_service.domain import lines

AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")
TERM_ID = UUID("77777777-7777-7777-7777-777777777777")

ACTIONS = "- Anna: send the pricing proposal — by Tuesday\n- Tom: book the room"
DISCUSSION = "We talked about pricing."


def _content(actions: str = ACTIONS, discussion: str = DISCUSSION) -> NoteContent:
    return NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="Weekly",
        sections=[
            NoteSection(section_key="discussion", text=discussion),
            NoteSection(section_key="action_items", text=actions),
        ],
    )


def _claims(sub: UUID = AUTHOR, tid: UUID = TENANT, roles: list[str] | None = None) -> Claims:
    return Claims(
        sub=sub,
        tid=tid,
        roles=roles or ["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note_row(version_number: int = 1, **over: object) -> SimpleNamespace:
    row = SimpleNamespace(
        id=NOTE_ID,
        tenant_id=TENANT,
        code="NOTE-2026-00042",
        status=NoteStatus.DRAFT,
        current_version_id=VERSION_ID,
        current_version_number=version_number,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        shared_with_ids=[],
        visibility="workspace",
        title="Weekly",
        source_asr_job_id=None,
        deleted_at=None,
    )
    for key, value in over.items():
        setattr(row, key, value)
    return row


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import glossary as rg
    from note_service.routers import notes_corrections as rc

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )

    store = SimpleNamespace(
        note=_note_row(),
        # version_number → content
        versions={1: _content()},
        corrections=[],
        dismissed=set(),
        terms=[],
        term_count=0,
    )

    conn = SimpleNamespace(
        execute=lambda *a, **k: None,
        fetchrow=lambda *a, **k: None,
        fetch=lambda *a, **k: [],
        fetchval=lambda *a, **k: 0,
    )

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield conn

    for module in (rc, rg):
        monkeypatch.setattr(module, "tenant_connection", _tenant_conn)

    # ── notes_repository ────────────────────────────────────────────
    async def _fetch_note(conn, *, note_id, include_deleted=False):  # noqa: ANN001
        return store.note

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return SimpleNamespace(content=store.versions[store.note.current_version_number])

    async def _fetch_version_by_number(conn, *, note_id, version_number):  # noqa: ANN001
        content = store.versions.get(version_number)
        return SimpleNamespace(content=content) if content else None

    async def _append_version(conn, **kwargs):  # noqa: ANN001, ANN003
        expected = kwargs["expected_version"]
        if expected != store.note.current_version_number:
            from note_service.domain.conflicts import OptimisticLockMismatchError

            raise OptimisticLockMismatchError(
                current_version=store.note.current_version_number,
                expected_version=expected,
            )
        number = expected + 1
        store.versions[number] = kwargs["new_content"]
        store.note.current_version_number = number
        return uuid4(), number

    monkeypatch.setattr(rc.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(rc.repo, "lock_note_for_update", _fetch_note)
    monkeypatch.setattr(rc.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(rc.repo, "fetch_version_by_number", _fetch_version_by_number)
    monkeypatch.setattr(rc.repo, "append_version", _append_version)

    # ── glossary_repository ─────────────────────────────────────────
    async def _record_correction(conn, **kwargs):  # noqa: ANN001, ANN003
        store.corrections.append(kwargs)
        if kwargs["action"] == "dismiss":
            store.dismissed.add(kwargs["item_key"])
        elif kwargs["action"] == "restore":
            store.dismissed.discard(kwargs["item_key"])

    async def _dismissed_keys(conn, *, note_id):  # noqa: ANN001
        return set(store.dismissed)

    async def _list_terms(conn):  # noqa: ANN001
        return list(store.terms)

    async def _find_term(conn, *, term):  # noqa: ANN001
        return next((t for t in store.terms if t.term.lower() == term.lower()), None)

    async def _count_terms(conn):  # noqa: ANN001
        return store.term_count or len(store.terms)

    async def _add_term(  # noqa: ANN001
        conn, *, tenant_id, term, kind, heard_as, created_by, source_note_id=None
    ):
        from note_service.domain.glossary_repository import GlossaryRow

        row = GlossaryRow(
            id=TERM_ID,
            term=term,
            kind=kind,
            heard_as=list(heard_as),
            created_by=created_by,
            created_at=datetime(2026, 9, 20, tzinfo=UTC),
            source_note_id=source_note_id,
        )
        store.terms.append(row)
        return row

    async def _merge_heard_as(conn, *, row, heard_as):  # noqa: ANN001
        from note_service.domain.glossary import clean_heard_as

        row.heard_as = clean_heard_as([*row.heard_as, *heard_as], term=row.term)
        return row

    async def _soft_delete(conn, *, term_id):  # noqa: ANN001
        row = next((t for t in store.terms if t.id == term_id), None)
        if row is not None:
            store.terms.remove(row)
        return row

    async def _terms_for_matching(conn):  # noqa: ANN001
        from note_service.domain.glossary import Term

        return [Term(t.term, t.kind, tuple(t.heard_as)) for t in store.terms]

    for module in (rc, rg):
        monkeypatch.setattr(module.glossary_repo, "record_correction", _record_correction)
        monkeypatch.setattr(module.glossary_repo, "dismissed_keys", _dismissed_keys)
        monkeypatch.setattr(module.glossary_repo, "list_terms", _list_terms)
        monkeypatch.setattr(module.glossary_repo, "find_term", _find_term)
        monkeypatch.setattr(module.glossary_repo, "count_terms", _count_terms)
        monkeypatch.setattr(module.glossary_repo, "add_term", _add_term)
        monkeypatch.setattr(module.glossary_repo, "merge_heard_as", _merge_heard_as)
        monkeypatch.setattr(module.glossary_repo, "soft_delete_term", _soft_delete)
        monkeypatch.setattr(module.glossary_repo, "terms_for_matching", _terms_for_matching)

    app = create_app()
    # A zero-arg override: FastAPI reads an override's OWN signature as
    # request parameters, and `_claims`'s `roles: list[str]` would be
    # taken for a body field.
    app.dependency_overrides[deps.current_user] = lambda: _claims()
    return SimpleNamespace(
        client=TestClient(app),
        store=store,
        audit_calls=audit_calls,
        app=app,
        deps=deps,
        monkeypatch=monkeypatch,
    )


def _key(body: str) -> str:
    return lines.key_of(body)


def _actions(rig: SimpleNamespace) -> str:
    content = rig.store.versions[rig.store.note.current_version_number]
    return next(s.text for s in content.sections if s.section_key == "action_items")


# ── Dismiss ─────────────────────────────────────────────────────────


def test_dismissing_a_line_removes_it_and_records_why(rig: SimpleNamespace) -> None:
    key = _key("send the pricing proposal")
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
        json={"expected_version": 1, "reason": "not_a_task"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version_number"] == 2
    assert _actions(rig) == "- Tom: book the room"

    (correction,) = rig.store.corrections
    assert correction["action"] == "dismiss"
    assert correction["reason"] == "not_a_task"
    assert correction["kind"] == "action"


def test_a_correction_never_records_the_line_text(rig: SimpleNamespace) -> None:
    key = _key("send the pricing proposal")
    rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
        json={"expected_version": 1, "reason": "not_said"},
    )
    blob = repr(rig.store.corrections) + repr(rig.audit_calls)
    for secret in ("pricing proposal", "Anna", "Tuesday"):
        assert secret not in blob


def test_dismissing_a_line_that_is_already_gone_is_not_an_error(
    rig: SimpleNamespace,
) -> None:
    key = _key("send the pricing proposal")
    body = {"expected_version": 1, "reason": "duplicate"}
    assert rig.client.post(f"/v1/notes/{NOTE_ID}/items/{key}/dismiss", json=body).status_code == 200
    again = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
        json={"expected_version": 2, "reason": "duplicate"},
    )
    assert again.status_code == 200
    assert len(rig.store.corrections) == 1  # not logged twice


def test_dismissing_an_unknown_line_is_a_404(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/0000000000000000/dismiss",
        json={"expected_version": 1, "reason": "not_said"},
    )
    assert resp.status_code == 404


def test_a_stale_expected_version_is_a_conflict(rig: SimpleNamespace) -> None:
    rig.store.note.current_version_number = 4
    rig.store.versions[4] = _content()
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{_key('book the room')}/dismiss",
        json={"expected_version": 1, "reason": "not_relevant"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "optimistic_lock_mismatch"


def test_a_reason_outside_the_vocabulary_is_refused(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{_key('book the room')}/dismiss",
        json={"expected_version": 1, "reason": "i just do not like it"},
    )
    assert resp.status_code == 422


# ── Restore ─────────────────────────────────────────────────────────


def test_a_dismissed_line_comes_back_exactly_as_it_read(rig: SimpleNamespace) -> None:
    key = _key("send the pricing proposal")
    rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
        json={"expected_version": 1, "reason": "not_a_task"},
    )
    resp = rig.client.post(f"/v1/notes/{NOTE_ID}/items/{key}/restore", json={"expected_version": 2})
    assert resp.status_code == 200, resp.text
    # Back at the bottom of its own section, word for word.
    assert _actions(rig) == "- Tom: book the room\n- Anna: send the pricing proposal — by Tuesday"
    assert resp.json()["line"] == "- Anna: send the pricing proposal — by Tuesday"
    assert [c["action"] for c in rig.store.corrections] == ["dismiss", "restore"]


def test_restoring_a_line_that_is_present_is_a_conflict(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{_key('book the room')}/restore",
        json={"expected_version": 1},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "already_present"


def test_restoring_something_this_note_never_had_is_a_404(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/0000000000000000/restore",
        json={"expected_version": 1},
    )
    assert resp.status_code == 404


def test_restore_cancels_the_dismissal(rig: SimpleNamespace) -> None:
    key = _key("send the pricing proposal")
    rig.client.post(
        f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
        json={"expected_version": 1, "reason": "not_a_task"},
    )
    rig.client.post(f"/v1/notes/{NOTE_ID}/items/{key}/restore", json={"expected_version": 2})
    assert key not in rig.store.dismissed


# ── Owner / due in place ────────────────────────────────────────────


def test_changing_the_owner_keeps_the_key(rig: SimpleNamespace) -> None:
    """The point of the whole design: a recipient's confirmation and (once
    Sprint 33 lands) the evidence chip hang off this key."""
    key = _key("send the pricing proposal")
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={"expected_version": 1, "owner_label": "Tom"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["item_key"] == key
    assert resp.json()["line"] == "- Tom: send the pricing proposal — Tuesday"
    # And the line is still findable under the SAME key afterwards.
    assert lines.find(_actions(rig), key) is not None
    assert rig.store.corrections[0]["action"] == "owner_changed"


def test_changing_the_due_date_keeps_the_key(rig: SimpleNamespace) -> None:
    key = _key("book the room")
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={"expected_version": 1, "due_text": "next Monday"},
    )
    assert resp.status_code == 200
    assert resp.json()["line"] == "- Tom: book the room — next Monday"
    assert lines.find(_actions(rig), key) is not None
    assert rig.store.corrections[0]["action"] == "due_changed"


def test_an_owner_can_be_cleared(rig: SimpleNamespace) -> None:
    key = _key("book the room")
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={"expected_version": 1, "clear_owner": True},
    )
    assert resp.json()["line"] == "- book the room"
    assert lines.find(_actions(rig), key) is not None


def test_a_patch_that_changes_nothing_writes_no_version(rig: SimpleNamespace) -> None:
    key = _key("book the room")
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={"expected_version": 1, "owner_label": "Tom"},
    )
    assert resp.status_code == 200
    assert resp.json()["version_number"] == 1
    assert rig.store.corrections == []


def test_a_patch_with_nothing_in_it_is_refused(rig: SimpleNamespace) -> None:
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{_key('book the room')}",
        json={"expected_version": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "nothing_to_change"


def test_the_sprint_20_status_route_still_works_beside_it(rig: SimpleNamespace) -> None:
    """`PATCH /items/{item_id}` addresses an item by its row UUID and has
    done since Sprint 20. `/items/by-key/{item_key}` must sit beside it,
    not swallow it — which is why the corrections route took an extra
    literal segment instead of the path the sprint plan wrote."""
    patches = {
        route.path: route.endpoint.__module__
        for route in rig.app.routes
        if "PATCH" in getattr(route, "methods", set()) and "/items/" in route.path
    }
    assert patches["/v1/notes/{note_id}/items/{item_id}"].endswith("notes_items")
    assert patches["/v1/notes/{note_id}/items/by-key/{item_key}"].endswith("notes_corrections")


# ── Another tenant ──────────────────────────────────────────────────


def test_another_tenant_gets_404_on_every_correction_route(rig: SimpleNamespace) -> None:
    rig.store.note = None
    rig.app.dependency_overrides[rig.deps.current_user] = lambda: _claims(sub=uuid4(), tid=uuid4())
    key = _key("book the room")
    for method, path, body in (
        (
            "post",
            f"/v1/notes/{NOTE_ID}/items/{key}/dismiss",
            {"expected_version": 1, "reason": "not_said"},
        ),
        ("post", f"/v1/notes/{NOTE_ID}/items/{key}/restore", {"expected_version": 1}),
        (
            "patch",
            f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
            {"expected_version": 1, "owner_label": "Tom"},
        ),
    ):
        resp = getattr(rig.client, method)(path, json=body)
        assert resp.status_code == 404, f"{path} → {resp.status_code}"


# ── Glossary ────────────────────────────────────────────────────────


def test_remembering_a_term(rig: SimpleNamespace) -> None:
    resp = rig.client.post(
        "/v1/glossary", json={"term": "John Mayer", "kind": "person", "heard_as": ["Jon Meyer"]}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["term"] == "John Mayer"
    assert body["heard_as"] == ["Jon Meyer"]
    assert body["can_delete"] is True
    (event,) = rig.audit_calls
    assert event["payload"] == {"kind": "person", "heard_as_count": 1}
    assert "Mayer" not in repr(event)  # the term itself is never audited


def test_remembering_the_same_term_again_teaches_the_new_mishearing(
    rig: SimpleNamespace,
) -> None:
    rig.client.post("/v1/glossary", json={"term": "John Mayer", "heard_as": ["Jon Meyer"]})
    # A case variant (a person still needs a capital somewhere — Sprint I2).
    resp = rig.client.post("/v1/glossary", json={"term": "John mayer", "heard_as": ["John Meyer"]})
    assert resp.status_code == 200  # merged, not a duplicate error
    assert resp.json()["heard_as"] == ["Jon Meyer", "John Meyer"]
    assert len(rig.store.terms) == 1


def test_a_full_glossary_refuses_the_next_term(rig: SimpleNamespace) -> None:
    from note_service.domain.glossary import MAX_TERMS

    rig.store.term_count = MAX_TERMS
    resp = rig.client.post("/v1/glossary", json={"term": "One More"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "glossary_full"


def test_a_term_with_control_characters_is_refused(rig: SimpleNamespace) -> None:
    resp = rig.client.post("/v1/glossary", json={"term": "John‮Mayer"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "term_invalid"


def test_the_hint_is_the_capture_forms_vocabulary(rig: SimpleNamespace) -> None:
    rig.client.post("/v1/glossary", json={"term": "Contoso", "kind": "company"})
    resp = rig.client.get("/v1/glossary/hint")
    assert resp.status_code == 200
    assert resp.json() == {"hint": "Contoso", "terms": 1}


def test_only_the_creator_or_an_admin_forgets_a_term(rig: SimpleNamespace) -> None:
    rig.client.post("/v1/glossary", json={"term": "Contoso", "kind": "company"})
    rig.app.dependency_overrides[rig.deps.current_user] = lambda: _claims(sub=uuid4())
    assert rig.client.delete(f"/v1/glossary/{TERM_ID}").status_code == 403

    rig.app.dependency_overrides[rig.deps.current_user] = lambda: _claims(
        sub=uuid4(), roles=["tenant_admin", "member"]
    )
    assert rig.client.delete(f"/v1/glossary/{TERM_ID}").status_code == 204
    assert rig.store.terms == []


def test_forgetting_a_term_that_is_not_there_is_a_404(rig: SimpleNamespace) -> None:
    assert rig.client.delete(f"/v1/glossary/{uuid4()}").status_code == 404


# ── Summary Engine v2, Q5: a respelled name, accepted or rejected ────

NAMED = "- Laut Fabian Reinbold wird die Mehrheit knapp\n- Tom: book the room"


def _named_rig(rig: SimpleNamespace) -> str:
    rig.store.versions[1] = _content(discussion=NAMED)
    return _key("Laut Fabian Reinbold wird die Mehrheit knapp")


def test_rejecting_a_correction_puts_back_what_was_heard(rig: SimpleNamespace) -> None:
    key = _named_rig(rig)
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={
            "expected_version": 1,
            "action": "correction_rejected",
            "reason": "wrong_name",
            "surface": "Fabian Reinbolt",
            "canonical": "Fabian Reinbold",
            "source": "candidate",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["line"] == "- Laut Fabian Reinbolt wird die Mehrheit knapp"
    # The line changed, so its key did: the response says which it is now.
    assert body["item_key"] == _key("Laut Fabian Reinbolt wird die Mehrheit knapp")
    assert "Fabian Reinbolt" in rig.store.versions[2].sections[0].text
    (correction,) = rig.store.corrections
    assert (correction["action"], correction["reason"]) == ("correction_rejected", "wrong_name")
    (event,) = [e for e in rig.audit_calls if e["kind"] == "note.correction_rejected"]
    # Never the name in the audit trail.
    assert "Reinbold" not in str(event["payload"]) and event["payload"]["source"] == "candidate"


def test_accepting_a_correction_changes_nothing_in_the_note(rig: SimpleNamespace) -> None:
    key = _named_rig(rig)
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={
            "expected_version": 1,
            "action": "correction_accepted",
            "surface": "Fabian Reinbolt",
            "canonical": "Fabian Reinbold",
            "source": "model",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["item_key"] == key
    assert 2 not in rig.store.versions  # no new version
    assert rig.store.corrections[0]["action"] == "correction_accepted"


def test_the_accepted_name_becomes_a_glossary_term_and_merges_next_time(
    rig: SimpleNamespace,
) -> None:
    first = rig.client.post(
        "/v1/glossary",
        json={"term": "Fabian Reinbold", "kind": "person", "heard_as": ["Fabian Reinbolt"]},
    )
    assert first.status_code in (200, 201)
    second = rig.client.post(
        "/v1/glossary",
        json={"term": "Fabian Reinbold", "kind": "person", "heard_as": ["Fabian Rainbold"]},
    )
    assert second.status_code in (200, 201)
    (term,) = rig.store.terms
    assert set(term.heard_as) == {"Fabian Reinbolt", "Fabian Rainbold"}


def test_rejecting_a_name_the_line_does_not_have_is_refused(rig: SimpleNamespace) -> None:
    key = _named_rig(rig)
    resp = rig.client.patch(
        f"/v1/notes/{NOTE_ID}/items/by-key/{key}",
        json={
            "expected_version": 1,
            "action": "correction_rejected",
            "surface": "Olaf",
            "canonical": "Olaf Scholz",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "correction_not_in_line"


# ── Sprint I2: only names and terms become vocabulary ──────────────


def test_a_role_label_is_refused_with_its_own_code(rig: SimpleNamespace) -> None:
    for term in ("Moderator II", "speaker background", "moderatorin", "Narrator"):
        resp = rig.client.post("/v1/glossary", json={"term": term, "kind": "person"})
        assert resp.status_code == 422, (term, resp.text)
        assert resp.json()["code"] == "term_not_vocabulary"
    assert rig.store.terms == [] and rig.audit_calls == []


def test_a_stored_role_label_is_shown_as_not_sent_and_left_out_of_the_hint(
    rig: SimpleNamespace,
) -> None:
    from note_service.domain.glossary_repository import GlossaryRow

    rig.store.terms.append(
        GlossaryRow(
            id=uuid4(),
            term="Moderator II",
            kind="person",
            heard_as=[],
            created_by=AUTHOR,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
    )
    rig.client.post("/v1/glossary", json={"term": "Gregor Gysi", "kind": "person"})
    listed = {t["term"]: t for t in rig.client.get("/v1/glossary").json()}
    assert listed["Moderator II"]["in_hint"] is False
    assert listed["Gregor Gysi"]["in_hint"] is True
    assert rig.client.get("/v1/glossary/hint").json() == {"hint": "Gregor Gysi", "terms": 2}


def test_a_term_remembered_from_a_note_records_where_it_came_from(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service.routers import glossary as rg

    async def _note_exists(conn, *, note_id):  # noqa: ANN001
        return note_id == NOTE_ID

    monkeypatch.setattr(rg.glossary_repo, "note_exists", _note_exists)
    resp = rig.client.post(
        "/v1/glossary", json={"term": "Gregor Gysi", "kind": "person", "note_id": str(NOTE_ID)}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source_note_id"] == str(NOTE_ID)
    (event,) = rig.audit_calls
    assert event["payload"] == {"kind": "person", "heard_as_count": 0, "note_id": str(NOTE_ID)}
    assert "Gysi" not in repr(event)

    # A note of another workspace (or none): the term is kept, the provenance is not.
    other = rig.client.post(
        "/v1/glossary", json={"term": "Pardo", "kind": "product", "note_id": str(uuid4())}
    )
    assert other.status_code == 201 and other.json()["source_note_id"] is None
