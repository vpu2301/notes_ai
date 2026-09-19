"""The anonymous shared page, end to end through the router (Sprint 19).

The first test of ``/v1/shared/{token}`` at all. The DB is a set of
repository doubles; the rate limiter is the real one over an in-memory
Redis stand-in, because "61st request in a minute → 429" and "Redis down
→ still 200" are the two behaviours the sprint has to prove.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from note_models import NoteContent, NoteSection, NoteStatus
from note_service.adapters.email import MockProvider
from note_service.config import settings
from note_service.domain import action_items_repository as items_repo
from note_service.domain import notes_repository as repo
from note_service.domain import recipient_mail, sharing_policy
from note_service.domain.branding import TenantBranding
from note_service.domain.public_rate_limit import PublicRateLimiter
from note_service.domain.share_tokens import hash_token, token_for

TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
LINK = UUID("66666666-6666-6666-6666-666666666666")
AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
TOKEN = token_for(LINK, key_hex=settings.share_link_hmac_key_hex)
BASE = "https://app.notes-ai.test"


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: set[str] = set()
        self.values: dict[str, object] = {}
        self.down = False

    async def set(
        self, key: str, value: object, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if self.down:
            raise ConnectionError("redis down")
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        self.values[key] = value
        return True

    async def get(self, key: str) -> object | None:
        if self.down:
            raise ConnectionError("redis down")
        return self.values.get(key)

    async def incrby(self, key: str, n: int) -> int:
        if self.down:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + n
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        if self.down:
            raise ConnectionError("redis down")


def _note(status: NoteStatus = NoteStatus.FINALIZED) -> repo.NoteRow:
    return repo.NoteRow(
        id=NOTE,
        tenant_id=TENANT,
        code="N-2026-0001",
        status=status,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[],
        title="Kickoff: Website relaunch",
        created_at=NOW,
        updated_at=NOW,
        finalized_at=NOW,
        cancelled_at=None,
    )


def _version(note: repo.NoteRow) -> repo.VersionRow:
    content = NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="Kickoff: Website relaunch",
        sections=[
            NoteSection(section_key="discussion", text="Long chat."),
            NoteSection(section_key="action_items", text="Send proposal — Anna"),
            NoteSection(section_key="attendees", text="Anna, Tom"),
            NoteSection(section_key="decisions", text="Go with option B."),
            NoteSection(section_key="agenda", text=""),
        ],
    )
    return repo.VersionRow(
        id=note.current_version_id,
        note_id=NOTE,
        version_number=1,
        parent_version_id=None,
        created_by=AUTHOR,
        created_at=NOW,
        content=content,
        rendered_text="",
        body_hash=None,
        is_amendment=False,
        amendment_type=None,
        amendment_reason=None,
    )


def _row_dict(row: repo.ShareLinkRow) -> dict:
    return {f: getattr(row, f) for f in row.__slots__}  # type: ignore[attr-defined]


def _link(**over) -> repo.ShareLinkRow:  # noqa: ANN003
    base: dict = {
        "id": LINK,
        "note_id": NOTE,
        "created_by": AUTHOR,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=90),
        "last_viewed_at": None,
        "view_count": 0,
        "kind": "recipient",
        "label": "Tom @ Client",
        "recipient_email": "tom@client.com",
        "ref_code": "abcdefghijkl",
    }
    base.update(over)
    return repo.ShareLinkRow(**base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import shared_public as router_mod

    monkeypatch.setattr(settings, "app_base_url", BASE)
    monkeypatch.setattr(settings, "product_brand_name", "Klarnote")

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    redis = FakeRedis()
    provider = MockProvider()
    limiter = PublicRateLimiter(redis, ip_per_minute=60, link_per_hour=300, cta_per_hour=20)
    limiter._limiter._clock = lambda: 1_700_000_000.0  # one fixed window

    @contextlib.asynccontextmanager
    async def _acquire():  # noqa: ANN202
        yield None

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=SimpleNamespace(acquire=_acquire),
            audit_writer=SimpleNamespace(write_event=_write_event),
            public_rate_limiter=limiter,
            redis=redis,
            email_provider=provider,
        )
    )
    emitted: list[dict] = []

    async def _emit(*args, **kwargs):  # noqa: ANN002, ANN003
        emitted.append(kwargs)

    monkeypatch.setattr(router_mod, "emit_note_event", _emit)

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    note = _note()
    world = {
        "note": note,
        "version": _version(note),
        "link": _link(),
        "views": 0,
        "cta": 0,
        "logo": None,
        "resolves": True,
        # Sprint 20: the items of the current version and this link's responses.
        "items": [
            items_repo.ItemRow(
                id=uuid4(),
                note_id=NOTE,
                note_version_id=note.current_version_id,
                item_key="k1",
                position=0,
                text="Send proposal",
                owner_label="Anna",
                owner_confidence=1.0,
                due_date=None,
                due_text=None,
                due_confidence=None,
                status="open",
            ),
        ],
        "responses": [],  # (kind, item_key, section_key, comment)
    }

    async def _fetch_items(conn, *, version_id):  # noqa: ANN001
        return world["items"] if version_id == world["note"].current_version_id else []

    async def _responses_for_link(conn, *, link_id):  # noqa: ANN001
        return [
            items_repo.ResponseRow(
                id=uuid4(),
                note_id=NOTE,
                link_id=LINK,
                link_label="Tom @ Client",
                kind=k,
                item_key=ik,
                section_key=sk,
                comment=c,
                created_at=NOW,
                cleared_at=None,
            )
            for (k, ik, sk, c) in world["responses"]
        ]

    async def _upsert(conn, *, tenant_id, note_id, link_id, kind, item_key, section_key, comment):  # noqa: ANN001
        world["responses"] = [
            r for r in world["responses"] if not (r[1] == item_key and r[2] == section_key)
        ]
        world["responses"].append((kind, item_key, section_key, comment))
        return uuid4()

    async def _withdraw(conn, *, link_id, item_key, section_key):  # noqa: ANN001
        before = len(world["responses"])
        world["responses"] = [
            r for r in world["responses"] if not (r[1] == item_key and r[2] == section_key)
        ]
        return before - len(world["responses"])

    for name, fn in {
        "fetch_items": _fetch_items,
        "responses_for_link": _responses_for_link,
        "upsert_response": _upsert,
        "withdraw_response": _withdraw,
    }.items():
        monkeypatch.setattr(items_repo, name, fn)

    async def _resolve(conn, *, token_hash):  # noqa: ANN001
        if world["resolves"] and token_hash == hash_token(TOKEN):
            return TENANT, NOTE, LINK
        return None

    async def _fetch_link(conn, *, link_id):  # noqa: ANN001
        return world["link"] if link_id == LINK else None

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return world["note"]

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001
        return world.get("versions", {}).get(version_id, world["version"])

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        return [SimpleNamespace(sub=AUTHOR, email="anna@acme.com", display_name="Anna Koval")]

    async def _record_view(conn, *, link_id):  # noqa: ANN001
        world["views"] += 1
        return world["views"] == 1

    async def _record_cta(conn, *, link_id):  # noqa: ANN001
        world["cta"] += 1
        return world["cta"] == 1

    async def _fetch_logo(conn, *, tenant_id):  # noqa: ANN001
        return world["logo"]

    world["suppressions"] = []
    world["suppressed_links"] = 0

    async def _tenant_of_link(conn, *, link_id):  # noqa: ANN001
        return TENANT if link_id == LINK else None

    async def _add_suppression(conn, *, email_hash, reason):  # noqa: ANN001
        world["suppressions"].append((email_hash, reason))

    async def _suppress_links(conn, *, tenant_id, email):  # noqa: ANN001
        world["suppressed_links"] += 1
        return 1

    world["policy"] = sharing_policy.SharingPolicy()
    world["plan"] = "free"
    world["seen"] = []
    world["otp"] = None  # (code_hash, live, attempts)
    world["reports"] = []
    world["spam_for_sender"] = 0
    world["saved_policy"] = None

    async def _load_policy(conn, *, tenant_id):  # noqa: ANN001
        return world["policy"], world["plan"]

    async def _save_policy(conn, *, tenant_id, policy):  # noqa: ANN001
        world["saved_policy"] = policy
        world["policy"] = policy

    monkeypatch.setattr(sharing_policy, "load_policy", _load_policy)
    monkeypatch.setattr(sharing_policy, "save_policy", _save_policy)

    async def _locale(conn, *, tenant_id):  # noqa: ANN001
        return "en"

    async def _seen(conn, *, link_id, version_id):  # noqa: ANN001
        world["seen"].append(version_id)

    async def _put_otp(conn, *, tenant_id, link_id, code_hash, ttl_seconds):  # noqa: ANN001
        world["otp"] = [code_hash, True, 0]

    async def _fetch_otp(conn, *, link_id):  # noqa: ANN001
        return tuple(world["otp"]) if world["otp"] else None

    async def _bump(conn, *, link_id):  # noqa: ANN001
        world["otp"][2] += 1
        return world["otp"][2]

    async def _del_otp(conn, *, link_id):  # noqa: ANN001
        world["otp"] = None

    async def _verified(conn, *, link_id):  # noqa: ANN001
        world["link"] = _link(**{**_row_dict(world["link"]), "verified_at": NOW})

    async def _report(conn, *, tenant_id, link_id, note_id, reason):  # noqa: ANN001
        world["reports"].append(reason)

    async def _spam(conn, *, created_by):  # noqa: ANN001
        return world["spam_for_sender"]

    for name, fn in {
        "fetch_tenant_locale": _locale,
        "mark_link_seen": _seen,
        "put_link_otp": _put_otp,
        "fetch_link_otp": _fetch_otp,
        "bump_link_otp_attempts": _bump,
        "delete_link_otp": _del_otp,
        "mark_link_verified": _verified,
        "add_abuse_report": _report,
        "spam_reports_for_sender": _spam,
        "tenant_of_share_link": _tenant_of_link,
        "add_share_mail_suppression": _add_suppression,
        "suppress_links_for_email": _suppress_links,
        "resolve_share_link": _resolve,
        "fetch_share_link": _fetch_link,
        "fetch_note": _fetch_note,
        "fetch_version": _fetch_version,
        "fetch_members": _fetch_members,
        "record_share_link_view": _record_view,
        "record_cta_click": _record_cta,
        "fetch_tenant_logo": _fetch_logo,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    async def _branding(conn, *, tenant_id):  # noqa: ANN001
        return TenantBranding(
            tenant_id=str(tenant_id),
            display_name="Acme Consulting",
            has_logo=world["logo"] is not None,
        )

    async def _labels(conn, *, content):  # noqa: ANN001
        return None  # template gone: raw keys are humanised by the client

    monkeypatch.setattr(router_mod, "load_tenant_branding", _branding)
    monkeypatch.setattr(router_mod, "_resolve_section_labels", _labels)

    c = TestClient(create_app())
    c.world = world  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.redis = redis  # type: ignore[attr-defined]
    c.emitted = emitted  # type: ignore[attr-defined]
    c.provider = provider  # type: ignore[attr-defined]
    return c


# ── the page ─────────────────────────────────────────────────────────


def test_page_carries_sender_product_and_section_roles(client: TestClient) -> None:
    r = client.get(f"/v1/shared/{TOKEN}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["sender"] == {
        "issuer_name": "Acme Consulting",
        "has_logo": False,
        "logo_path": None,
        "shared_by_display": "Anna Koval",
    }
    assert body["product"] == {
        "brand_name": "Klarnote",
        "header_text": "Meeting summary generated by Klarnote. Create your own workspace free.",
        "cta_path": f"/v1/shared/{TOKEN}/cta",
        "cta_enabled": True,
    }
    assert "is_draft" not in body
    assert body["expires_at"] is not None
    assert [(s["section_key"], s["role"]) for s in body["sections"]] == [
        ("discussion", "other"),
        ("action_items", "action_items"),
        ("attendees", "attendees"),
        ("decisions", "decisions"),
    ]
    assert "tom@client.com" not in r.text


def test_first_view_is_counted_once(client: TestClient) -> None:
    client.get(f"/v1/shared/{TOKEN}")
    client.get(f"/v1/shared/{TOKEN}")
    views = [c["payload"] for c in client.audit if c["kind"] == "note.viewed_via_link"]
    assert [v["first_view"] for v in views] == [True, False]
    assert all(v["kind"] == "recipient" for v in views)
    assert "tom@client.com" not in repr(client.audit)
    assert TOKEN not in repr(client.audit)


@pytest.mark.parametrize("token", ["short", TOKEN[:-1] + "x", "x" * 43])
def test_unknown_or_malformed_token_is_404(client: TestClient, token: str) -> None:
    assert client.get(f"/v1/shared/{token}").status_code == 404


def test_revoked_link_is_404(client: TestClient) -> None:
    client.world["resolves"] = False
    assert client.get(f"/v1/shared/{TOKEN}").status_code == 404
    assert client.get(f"/v1/shared/{TOKEN}/cta").status_code == 404


def test_cancelled_note_is_404(client: TestClient) -> None:
    client.world["note"] = _note(NoteStatus.CANCELLED)
    assert client.get(f"/v1/shared/{TOKEN}").status_code == 404


# ── the CTA ──────────────────────────────────────────────────────────


def test_cta_redirects_to_join_with_ref_and_counts_once(client: TestClient) -> None:
    r = client.get(f"/v1/shared/{TOKEN}/cta", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"{BASE}/join?ref=abcdefghijkl"
    client.get(f"/v1/shared/{TOKEN}/cta", follow_redirects=False)
    assert client.world["cta"] == 2
    assert [c["kind"] for c in client.audit].count("note.cta_clicked") == 1


def test_public_link_cta_has_no_ref(client: TestClient) -> None:
    client.world["link"] = _link(kind="public", label="", recipient_email=None, ref_code=None)
    r = client.get(f"/v1/shared/{TOKEN}/cta", follow_redirects=False)
    assert r.headers["location"] == f"{BASE}/join"


# ── the logo ─────────────────────────────────────────────────────────


def test_logo_404_without_one_and_cached_bytes_with_one(client: TestClient) -> None:
    assert client.get(f"/v1/shared/{TOKEN}/logo").status_code == 404
    client.world["logo"] = (b"\x89PNG...", "image/png")
    client.redis.values.clear()  # Sprint 23: "no logo" is cached for an hour
    r = client.get(f"/v1/shared/{TOKEN}/logo")
    assert r.status_code == 200
    assert r.content == b"\x89PNG..."
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "public, max-age=3600"
    etag = r.headers["etag"]
    again = client.get(f"/v1/shared/{TOKEN}/logo", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert client.get(f"/v1/shared/{TOKEN}").json()["sender"]["logo_path"] == (
        f"/v1/shared/{TOKEN}/logo"
    )


# ── rate limits ──────────────────────────────────────────────────────


def test_sixty_first_request_in_a_minute_is_429(client: TestClient) -> None:
    for _ in range(60):
        assert client.get(f"/v1/shared/{TOKEN}").status_code == 200
    r = client.get(f"/v1/shared/{TOKEN}")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["code"] == "rate_limited"


def test_redis_down_fails_open(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    client.redis.down = True
    with caplog.at_level("WARNING"):
        assert client.get(f"/v1/shared/{TOKEN}").status_code == 200
    assert any("ratelimit.backend_error" in rec.message for rec in caplog.records)


# ── Sprint 20: the recipient acts ────────────────────────────────────


def _respond(client: TestClient, kind: str = "confirm", key: str = "k1", **extra):  # noqa: ANN003
    return client.put(f"/v1/shared/{TOKEN}/items/{key}/response", json={"kind": kind, **extra})


def test_page_lists_items_and_can_respond(client: TestClient) -> None:
    body = client.get(f"/v1/shared/{TOKEN}").json()
    assert body["can_respond"] is True
    assert body["my_flags"] == []
    assert body["items"] == [
        {
            "item_key": "k1",
            "text": "Send proposal",
            "owner_label": "Anna",
            "due_date": None,
            "due_text": None,
            "status": "open",
            "my_response": None,
            "my_comment": None,
        }
    ]


def test_confirm_then_dispute_replaces_and_shows_up_as_mine(client: TestClient) -> None:
    assert _respond(client, "confirm").status_code == 200
    assert client.get(f"/v1/shared/{TOKEN}").json()["items"][0]["my_response"] == "confirm"
    assert _respond(client, "dispute", comment="It was Friday, not Tuesday").status_code == 200
    item = client.get(f"/v1/shared/{TOKEN}").json()["items"][0]
    assert item["my_response"] == "dispute"
    assert item["my_comment"] == "It was Friday, not Tuesday"
    # One stance per item: the dispute replaced the confirm.
    assert len(client.world["responses"]) == 1
    assert client.delete(f"/v1/shared/{TOKEN}/items/k1/response").status_code == 200
    assert client.get(f"/v1/shared/{TOKEN}").json()["items"][0]["my_response"] is None


def test_public_link_reads_items_but_cannot_respond(client: TestClient) -> None:
    client.world["link"] = _link(kind="public", label="", recipient_email=None, ref_code=None)
    assert client.get(f"/v1/shared/{TOKEN}").json()["can_respond"] is False
    r = _respond(client)
    assert r.status_code == 403
    assert r.json()["code"] == "link_kind_public"


@pytest.mark.parametrize(
    ("kind", "comment", "code"),
    [
        ("dispute", "see http://evil.example", 422),
        ("dispute", "x" * 281, 422),
        ("confirm", "not allowed here", 422),
    ],
)
def test_bad_comments_are_refused(client: TestClient, kind: str, comment: str, code: int) -> None:
    assert _respond(client, kind, comment=comment).status_code == code
    assert client.world["responses"] == []


def test_control_characters_are_stripped_from_a_comment(client: TestClient) -> None:
    assert _respond(client, "dispute", comment="  wrong\x00 date\x07 ").status_code == 200
    assert client.world["responses"][0][3] == "wrong date"


def test_unknown_or_old_item_key_is_404(client: TestClient) -> None:
    assert _respond(client, key="nope").status_code == 404


def test_flag_and_unflag_a_section(client: TestClient) -> None:
    r = client.put(f"/v1/shared/{TOKEN}/sections/decisions/flag", json={"comment": "not agreed"})
    assert r.status_code == 200
    assert client.get(f"/v1/shared/{TOKEN}").json()["my_flags"] == ["decisions"]
    assert client.put(f"/v1/shared/{TOKEN}/sections/nope/flag", json={}).status_code == 404
    assert client.delete(f"/v1/shared/{TOKEN}/sections/decisions/flag").status_code == 200
    assert client.get(f"/v1/shared/{TOKEN}").json()["my_flags"] == []


def test_author_is_told_once_per_link_per_window(client: TestClient) -> None:
    _respond(client, "confirm")
    _respond(client, "done")
    client.put(f"/v1/shared/{TOKEN}/sections/decisions/flag", json={})
    assert len(client.emitted) == 1
    event = client.emitted[0]
    assert event["primary_author_id"] == AUTHOR
    assert event["extra_payload"] == {"link_label": "Tom @ Client", "kind": "confirm"}
    responded = [c for c in client.audit if c["kind"] == "note.recipient_responded"]
    assert [c["payload"]["kind"] for c in responded] == ["confirm", "done", "flag"]
    assert all(c["payload"]["target"] in ("item", "section") for c in responded)
    assert "Send proposal" not in repr(client.audit)


def test_sixty_first_write_on_one_link_is_429(client: TestClient) -> None:
    # Lift the per-IP cap so the per-link write cap is what trips.
    from note_service.deps import get_state

    get_state().public_rate_limiter._ip_per_minute = 10_000
    for _ in range(60):
        assert _respond(client).status_code == 200
    r = _respond(client)
    assert r.status_code == 429
    assert r.json()["scope"] == "write"


# ── Sprint 22: one-click opt-out ─────────────────────────────────────


def test_unsubscribe_with_a_valid_signature_suppresses_the_address(client: TestClient) -> None:

    r = client.get(f"/v1/shared/unsubscribe/{recipient_mail.unsubscribe_token(LINK)}")
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()
    assert "tom@client.com" not in r.text
    assert client.world["suppressions"] == [
        (recipient_mail.email_hash("tom@client.com"), "unsubscribed")
    ]
    assert client.world["suppressed_links"] == 1
    kinds = [c["kind"] for c in client.audit]
    assert kinds.count("note.recipient_unsubscribed") == 1
    assert "tom@client.com" not in repr(client.audit)


def test_unsubscribe_with_a_forged_signature_changes_nothing_and_looks_the_same(
    client: TestClient,
) -> None:

    good = client.get(f"/v1/shared/unsubscribe/{recipient_mail.unsubscribe_token(LINK)}").text
    client.world["suppressions"].clear()
    payload = recipient_mail.unsubscribe_token(LINK).split(".")[0]
    bad = client.get(f"/v1/shared/unsubscribe/{payload}.{'0' * 32}")
    assert bad.status_code == 200
    assert bad.text == good
    assert client.world["suppressions"] == []


def test_first_open_of_a_recipient_link_tells_the_sender(client: TestClient) -> None:
    client.get(f"/v1/shared/{TOKEN}")
    client.get(f"/v1/shared/{TOKEN}")
    opened = [e for e in client.emitted if e["extra_payload"].get("delivery_status") == "opened"]
    assert len(opened) == 1
    assert opened[0]["extra_payload"] == {"link_label": "Tom @ Client", "delivery_status": "opened"}


# ── Sprint 23: policy on the page ────────────────────────────────────


def test_cta_can_be_turned_off_only_on_a_paid_plan(client: TestClient) -> None:
    client.world["policy"] = sharing_policy.SharingPolicy(cta_enabled=False)
    assert client.get(f"/v1/shared/{TOKEN}").json()["product"]["cta_enabled"] is True
    client.world["plan"] = "pro"
    assert client.get(f"/v1/shared/{TOKEN}").json()["product"]["cta_enabled"] is False


def test_verification_gate(client: TestClient) -> None:
    client.world["policy"] = sharing_policy.SharingPolicy(verified_recipients_required=True)
    page = client.get(f"/v1/shared/{TOKEN}").json()
    assert page["requires_verification"] is True
    assert page["can_respond"] is False
    r = _respond(client)
    assert r.status_code == 403
    assert r.json()["code"] == "verification_required"

    assert client.post(f"/v1/shared/{TOKEN}/verify/request").status_code == 202
    (mail,) = client.provider.sent
    assert mail.to_address == "tom@client.com"
    code = mail.subject.split(":")[-1].strip()
    assert len(code) == 6 and code.isdigit()
    assert "http" not in mail.text_body

    for _ in range(5):
        bad = client.post(f"/v1/shared/{TOKEN}/verify", json={"code": "000000"})
        assert bad.status_code == 400
        assert bad.json()["code"] == "code_invalid"
    assert client.post(f"/v1/shared/{TOKEN}/verify", json={"code": code}).status_code == 429
    assert client.world["otp"] is None

    client.post(f"/v1/shared/{TOKEN}/verify/request")
    code = client.provider.sent[-1].subject.split(":")[-1].strip()
    ok = client.post(f"/v1/shared/{TOKEN}/verify", json={"code": f"{code[:3]} {code[3:]}"})
    assert ok.status_code == 200
    assert ok.json()["can_respond"] is True
    assert ok.json()["requires_verification"] is False
    assert _respond(client).status_code == 200
    kinds = [c["kind"] for c in client.audit]
    assert "note.recipient_verified" in kinds and "note.recipient_verification_requested" in kinds
    assert code not in repr(client.audit)


def test_changes_since_last_view(client: TestClient) -> None:
    note = client.world["note"]
    old_version = client.world["version"]
    new_version = _version(note)
    new_version.id = uuid4()
    new_version.version_number = 2
    new_version.content.sections[3].text = "Go with option C."
    client.world["versions"] = {old_version.id: old_version, new_version.id: new_version}
    client.world["version"] = old_version
    # The page was loaded once on the old version.
    client.get(f"/v1/shared/{TOKEN}")
    client.world["link"] = _link(
        **{**_row_dict(client.world["link"]), "last_seen_version_id": old_version.id}
    )
    client.world["version"] = new_version
    note.current_version_id = new_version.id
    body = client.get(f"/v1/shared/{TOKEN}").json()
    assert body["changes"]["sections_changed"] == ["decisions"]
    assert body["changes"]["since_version"] == 1
    assert client.world["seen"][-1] == new_version.id
    client.world["link"] = _link(
        **{**_row_dict(client.world["link"]), "last_seen_version_id": new_version.id}
    )
    assert client.get(f"/v1/shared/{TOKEN}").json()["changes"] is None


def test_page_lang_follows_the_template_then_the_workspace(client: TestClient) -> None:
    body = client.get(f"/v1/shared/{TOKEN}").json()
    assert body["lang"] == "en"
    assert body["product"]["header_text"].startswith("Meeting summary generated by Klarnote")


def test_report_records_and_three_spam_reports_disable_product_mail(client: TestClient) -> None:
    r = client.post(f"/v1/shared/{TOKEN}/report", json={"reason": "inaccurate"})
    assert r.status_code == 202
    assert client.world["reports"] == ["inaccurate"]
    assert client.world["saved_policy"] is None
    client.world["spam_for_sender"] = 3
    client.post(f"/v1/shared/{TOKEN}/report", json={"reason": "spam"})
    saved = client.world["saved_policy"]
    assert saved is not None and saved.product_email_enabled is False
    assert saved.auto_disabled_reason == "abuse_reports"
    reported = [c for c in client.audit if c["kind"] == "note.link_reported"]
    assert reported[-1]["payload"]["auto_disabled"] is True
    assert any(e["category"].value == "share.reported" for e in client.emitted)
    assert client.post(f"/v1/shared/{TOKEN}/report", json={"reason": "nope"}).status_code == 422


def test_anonymous_cors_is_open_and_the_rest_is_not(client: TestClient) -> None:
    pre = client.options(
        f"/v1/shared/{TOKEN}",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert pre.status_code == 204
    assert pre.headers["access-control-allow-origin"] == "*"
    got = client.get(f"/v1/shared/{TOKEN}", headers={"Origin": "https://evil.example"})
    assert got.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in got.headers
    other = client.options(
        "/v1/notes/search",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert other.status_code == 400


def test_logo_is_served_from_redis_after_the_first_read(client: TestClient) -> None:
    client.world["logo"] = (b"\x89PNG", "image/png")
    assert client.get(f"/v1/shared/{TOKEN}/logo").status_code == 200
    client.world["logo"] = None
    assert client.get(f"/v1/shared/{TOKEN}/logo").content == b"\x89PNG"


def test_external_sharing_flag_off_darkens_recipient_links(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "external_sharing_enabled", False)
    assert client.get(f"/v1/shared/{TOKEN}").status_code == 404


def test_a_dialogue_section_is_the_transcript(client: TestClient) -> None:
    from note_service.routers.shared_public import _is_transcript

    assert _is_transcript("Anna: we ship Friday.\n\nTom: fine by me.\n\nAnna: done.")
    assert _is_transcript("Speaker 1: eins\n\nUnknown speaker: zwei\n\nNote to self")
    assert not _is_transcript("Anna, Tom")
    assert not _is_transcript("Decision: ship it.\n\nWe discussed the roadmap at length.")
    assert not _is_transcript("https://x.test: a\n\nhttps://y.test: b")
