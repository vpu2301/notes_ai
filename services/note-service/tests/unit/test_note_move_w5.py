"""W5: the family rule, the moved-note stub, the media re-home, the backfill rule and the
move/copy routes. Real handlers, DB stubbed; the SQL itself is pinned by
tests/integration/test_note_move_db.py."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import access, note_move, relocation, visibility
from note_service.domain import notes_repository as repo
from note_service.jobs import rehome_media

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
TARGET = UUID("77777777-7777-7777-7777-777777777777")
NOTE = UUID("33333333-3333-3333-3333-333333333333")
COLLEAGUE = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


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
        "code": "NOTE-2026-00412",
        "status": repo.NoteStatus.DRAFT,
        "current_version_id": uuid4(),
        "current_version_number": 1,
        "primary_author_id": USER,
        "co_author_ids": [],
        "title": "Client call",
        "created_at": NOW,
        "updated_at": NOW,
        "finalized_at": None,
        "cancelled_at": None,
        "visibility": "workspace",
    }
    base.update(over)
    return repo.NoteRow(**base)


# ── The family rule ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("meeting_type", "detected", "template", "expected"),
    [
        (None, None, None, "workspace"),
        ("client", "client", "client_call_en", "workspace"),
        ("one_on_one", None, None, "private"),
        ("interview", None, None, "private"),
        ("auto", "voice_memo", None, "private"),
        ("auto", "one_on_one", None, "private"),
        (None, None, "interview_debrief_de", "private"),
        (None, None, "ONE_ON_ONE_en", "private"),
        (None, None, "voice_memo", "private"),
        ("team", "podcast_broadcast", "team_meeting_en", "workspace"),
    ],
)
def test_default_for_note_in_a_team_workspace(
    meeting_type: str | None, detected: str | None, template: str | None, expected: str
) -> None:
    got = visibility.default_for_note(
        "team", meeting_type=meeting_type, meeting_type_detected=detected, template_code=template
    )
    assert got == expected


def test_personal_is_always_private() -> None:
    assert (
        visibility.default_for_note(
            "personal", meeting_type="client", meeting_type_detected=None, template_code=None
        )
        == "private"
    )


def test_the_sql_twin_lists_the_same_signals() -> None:
    """0078's `default_visibility_for_note` hard-codes these; a new private family must reach it."""
    sql = (
        Path(__file__).resolve().parents[4]
        / "infra/postgres/migrations/0078_move_note_to_workspace.sql"
    ).read_text()
    for value in visibility.SENSITIVE_MEETING_TYPES | visibility.SENSITIVE_DETECTED:
        assert f"'{value}'" in sql, value
    for prefix in visibility.SENSITIVE_TEMPLATE_PREFIXES:
        assert f"'{prefix}')" in sql, prefix


# ── The transcript closes while media is on its way ─────────────────


def test_no_transcript_for_anyone_while_rehoming() -> None:
    claims = _claims()
    assert access.can_read_transcript(_note(), claims)
    assert not access.can_read_transcript(_note(media_state="rehoming"), claims)
    assert not access.can_read_transcript(_note(media_state="failed"), claims)


# ── Who is told where a note went ───────────────────────────────────


def _stub(**over) -> relocation.Relocation:  # noqa: ANN003
    base: dict = {
        "note_id": NOTE,
        "to_tenant_id": TARGET,
        "old_code": "NOTE-2026-00412",
        "new_code": "NOTE-2026-00007",
        "was_workspace_visible": False,
        "author_team": [USER],
        "collaborator_subs": [],
    }
    base.update(over)
    return relocation.Relocation(**base)


def test_the_author_is_told() -> None:
    assert relocation.may_be_told(_stub(), _claims(USER))


def test_a_member_is_told_only_when_the_note_was_workspace_visible() -> None:
    assert not relocation.may_be_told(_stub(), _claims(COLLEAGUE))
    assert relocation.may_be_told(_stub(was_workspace_visible=True), _claims(COLLEAGUE))


def test_a_collaborator_is_told_and_a_guest_is_not() -> None:
    assert relocation.may_be_told(_stub(collaborator_subs=[COLLEAGUE]), _claims(COLLEAGUE, "guest"))
    assert not relocation.may_be_told(
        _stub(was_workspace_visible=True), _claims(COLLEAGUE, "guest")
    )


def test_moved_error_carries_only_the_destination_id() -> None:
    err = relocation.moved_error(_stub())
    assert err.status_code == 404
    assert err.detail == {
        "code": "note_moved",
        "detail": "this note was moved to another workspace",
        "to_workspace_id": str(TARGET),
    }


# ── Re-home, one object ─────────────────────────────────────────────


class FakeStore:
    """Objects keyed by name, sealed with (tenant, aad); `fail_delete` raises once."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[UUID, bytes, bytes]] = {}
        self.puts = 0
        self.fail_delete = False

    async def exists(self, *, key: str) -> bool:
        return key in self.objects

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        sealed_for, sealed_aad, data = self.objects[key]
        assert sealed_for == tenant_id, "tenant mismatch"
        assert sealed_aad == aad, "aad mismatch"
        return data

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.puts += 1
        self.objects[key] = (tenant_id, aad, plaintext)

    async def delete(self, *, key: str) -> None:
        if self.fail_delete:
            self.fail_delete = False
            raise RuntimeError("store down")
        self.objects.pop(key, None)


JOB = uuid4()


def _item(key: str | None = None) -> rehome_media.Item:
    return rehome_media.Item(
        "transcripts",
        key or f"{TENANT}/{JOB}.json.enc",
        JOB.bytes,
        "transcription_jobs",
        "result_storage_uri",
        JOB,
    )


async def _rehome(store: FakeStore, item: rehome_media.Item, pointed: list[str]) -> int:
    async def _point(it: rehome_media.Item, new_key: str) -> None:
        pointed.append(new_key)

    return await rehome_media.rehome_one(
        store=store, item=item, from_tenant=TENANT, to_tenant=TARGET, point_row_at=_point
    )


@pytest.mark.asyncio
async def test_an_object_is_resealed_for_the_new_workspace_and_the_old_copy_goes() -> None:
    store = FakeStore()
    store.objects[f"{TENANT}/{JOB}.json.enc"] = (TENANT, JOB.bytes, b"transcript")
    pointed: list[str] = []
    assert await _rehome(store, _item(), pointed) == len(b"transcript")
    assert list(store.objects) == [f"{TARGET}/{JOB}.json.enc"]
    assert store.objects[f"{TARGET}/{JOB}.json.enc"][0] == TARGET
    assert pointed == [f"{TARGET}/{JOB}.json.enc"]


@pytest.mark.asyncio
async def test_a_crash_after_the_put_is_finished_by_the_next_attempt_without_a_second_put() -> None:
    store = FakeStore()
    store.objects[f"{TENANT}/{JOB}.json.enc"] = (TENANT, JOB.bytes, b"transcript")
    store.fail_delete = True
    with pytest.raises(RuntimeError):
        await _rehome(store, _item(), [])
    assert len(store.objects) == 2  # two copies, never zero
    await _rehome(store, _item(), [])
    assert store.puts == 1
    assert list(store.objects) == [f"{TARGET}/{JOB}.json.enc"]


@pytest.mark.asyncio
async def test_a_revision_that_was_never_made_is_nothing_to_do() -> None:
    store = FakeStore()
    pointed: list[str] = []
    assert await _rehome(store, _item(f"{TENANT}/{JOB}.r3.json.enc"), pointed) == 0
    assert pointed == [] and store.objects == {}


@pytest.mark.asyncio
async def test_a_key_already_under_the_new_workspace_is_left_alone() -> None:
    store = FakeStore()
    store.objects[f"{TARGET}/{JOB}.json.enc"] = (TARGET, JOB.bytes, b"t")
    assert await _rehome(store, _item(f"{TARGET}/{JOB}.json.enc"), []) == 0
    assert store.puts == 0


def test_a_dictation_key_keeps_its_prefix() -> None:
    session = uuid4()
    assert (
        rehome_media.new_key_for(
            f"dictations/{TENANT}/{session}.wav.enc", from_tenant=TENANT, to_tenant=TARGET
        )
        == f"dictations/{TARGET}/{session}.wav.enc"
    )


# ── The backfill rule ───────────────────────────────────────────────


def _backfill_module():  # noqa: ANN202
    path = Path(__file__).resolve().parents[4] / "scripts/ops/backfill_workspace_visibility.py"
    spec = importlib.util.spec_from_file_location("backfill_workspace_visibility", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_workspace_visibility"] = module
    spec.loader.exec_module(module)
    return module


def test_backfill_skips_person_centred_notes_and_author_choices() -> None:
    backfill = _backfill_module()
    plain, one_on_one, memo, chosen = uuid4(), uuid4(), uuid4(), uuid4()

    def row(note_id: UUID, **over) -> dict:  # noqa: ANN003
        base = {
            "id": note_id,
            "primary_author_id": USER,
            "meeting_type": "client",
            "meeting_type_detected": None,
            "template_code": "client_call_en",
        }
        return {**base, **over}

    plan = backfill.classify(
        [
            row(plain),
            row(one_on_one, meeting_type="one_on_one"),
            row(memo, meeting_type="auto", meeting_type_detected="voice_memo"),
            row(chosen),
        ],
        {str(chosen)},
    )
    assert plan.change == [(plain, USER)]
    assert plan.sensitive == [one_on_one, memo]
    assert plan.author_choice == [chosen]


# ── Routes ──────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_move as router_mod

    audit_calls: list[dict] = []
    notified: list[dict] = []
    cache: dict[str, str] = {}

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    class _Redis:
        async def get(self, key: str) -> str | None:
            return cache.get(key)

        async def set(self, key: str, value: str, ex: int) -> None:
            cache[key] = value

        async def delete(self, key: str) -> None:
            cache.pop(key, None)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            redis=_Redis(),
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    async def _emit(*args, **kwargs):  # noqa: ANN002, ANN003
        notified.append(kwargs)

    monkeypatch.setattr(router_mod, "emit_note_event", _emit)

    state: dict = {"note": _note(), "moves": 0, "refuse": None}

    async def _fetch_note(conn, *, note_id, include_deleted=False):  # noqa: ANN001
        return state["note"]

    monkeypatch.setattr(repo, "fetch_note", _fetch_note)

    async def _move(*, app_pool, note, actor, to_tenant_id):  # noqa: ANN001
        if state["refuse"]:
            raise note_move.RefusedError(state["refuse"])
        state["moves"] += 1
        return note_move.Moved(
            note_id=note.id,
            from_tenant_id=note.tenant_id,
            to_tenant_id=to_tenant_id,
            code="NOTE-2026-00007",
            visibility="workspace",
            media_state="rehoming",
            job_id=JOB,
            audio_ids=[uuid4()],
        )

    monkeypatch.setattr(note_move, "move", _move)

    app = create_app()
    app.dependency_overrides[deps.current_user] = lambda: _claims()
    c = TestClient(app)
    c.app_ = app  # type: ignore[attr-defined]
    c.state_ = state  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.notified = notified  # type: ignore[attr-defined]
    return c


def _as(client: TestClient, claims: Claims) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: claims  # type: ignore[attr-defined]


def _body() -> dict:
    return {"workspace_id": str(TARGET), "client_mutation_id": str(uuid4())}


def test_move_answers_the_new_place_and_audits_both_chains(client: TestClient) -> None:
    r = client.post(f"/v1/notes/{NOTE}/move", json=_body())
    assert r.status_code == 200, r.text
    assert r.json() == {
        "note_id": str(NOTE),
        "workspace_id": str(TARGET),
        "code": "NOTE-2026-00007",
        "visibility": "workspace",
        "media_state": "rehoming",
    }
    by_kind = {(c["kind"], c["tenant_id"]) for c in client.audit}  # type: ignore[attr-defined]
    assert ("note.moved", TENANT) in by_kind
    assert ("note.moved_in", TARGET) in by_kind
    # The author moved their own note: nobody to tell.
    assert client.notified == []  # type: ignore[attr-defined]


def test_a_replayed_mutation_moves_once(client: TestClient) -> None:
    body = _body()
    first = client.post(f"/v1/notes/{NOTE}/move", json=body)
    second = client.post(f"/v1/notes/{NOTE}/move", json=body)
    assert first.json() == second.json()
    assert client.state_["moves"] == 1  # type: ignore[attr-defined]


def test_an_admin_moving_a_colleagues_note_tells_the_author(client: TestClient) -> None:
    _as(client, _claims(COLLEAGUE, "tenant_admin", "member"))
    r = client.post(f"/v1/notes/{NOTE}/move", json=_body())
    assert r.status_code == 200
    (event,) = client.notified  # type: ignore[attr-defined]
    assert event["primary_author_id"] == USER
    assert event["extra_payload"] == {"to_workspace_id": str(TARGET)}
    assert event["tenant_id"] == TENANT


def test_a_member_who_did_not_write_it_cannot_move_it(client: TestClient) -> None:
    _as(client, _claims(COLLEAGUE, "member"))
    r = client.post(f"/v1/notes/{NOTE}/move", json=_body())
    assert r.status_code == 403
    assert r.json()["code"] == "insufficient_role"
    assert client.state_["moves"] == 0  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("code", "http"),
    [
        ("not_a_member", 403),
        ("target_unavailable", 409),
        ("media_shared", 409),
        ("generation_in_progress", 409),
        ("same_workspace", 409),
    ],
)
def test_function_refusals_map_to_http(client: TestClient, code: str, http: int) -> None:
    client.state_["refuse"] = code  # type: ignore[attr-defined]
    r = client.post(f"/v1/notes/{NOTE}/move", json=_body())
    assert r.status_code == http
    assert r.json()["code"] == code
    assert not [c for c in client.audit if c["kind"] == "note.moved"]  # type: ignore[attr-defined]


def test_destinations_say_who_may_move(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _blockers(conn, *, note):  # noqa: ANN001
        return ["media_shared"]

    monkeypatch.setattr(note_move, "blockers", _blockers)
    r = client.get(f"/v1/notes/{NOTE}/destinations")
    assert r.json() == {
        "can_move": True,
        "can_copy": True,
        "eligible_roles": ["owner", "admin", "member"],
        "blockers": ["media_shared"],
    }
    _as(client, _claims(COLLEAGUE, "viewer"))
    r = client.get(f"/v1/notes/{NOTE}/destinations")
    assert r.json()["can_move"] is False and r.json()["blockers"] == []


def test_moved_view_survives_the_idempotency_cache() -> None:
    view = {
        "note_id": str(NOTE),
        "workspace_id": str(TARGET),
        "code": "c",
        "visibility": "private",
        "media_state": "ready",
    }
    from note_service.routers.notes_move import MovedView

    assert MovedView.model_validate(json.loads(MovedView(**view).model_dump_json())).code == "c"
