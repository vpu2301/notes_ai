"""Per-recipient share links (Sprint 19, migration 0035).

Mirrors ``test_share_by_email``: the real handlers run against an
overridden auth dependency and monkeypatched repository functions.

What is worth pinning: that any live note can be shared (0042 removed
the finalized-only gate), that a note can hold several live links at once, that the
same address gets the same link back, that revoking one leaves the
others alone, and that nobody outside the author team (or an admin) can
touch any of it.
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
from note_service.adapters.email import MockProvider
from note_service.config import settings
from note_service.domain import action_items_repository as items_repo
from note_service.domain import notes_repository as repo
from note_service.domain import sharing_policy
from note_service.domain.branding import TenantBranding

USER = UUID("11111111-1111-1111-1111-111111111111")
OTHER = UUID("12121212-1212-1212-1212-121212121212")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _claims(sub: UUID = USER, roles: list[str] | None = None) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=roles or ["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note(status: NoteStatus = NoteStatus.FINALIZED, title: str = "Acme kickoff") -> repo.NoteRow:
    return repo.NoteRow(
        id=NOTE,
        tenant_id=TENANT,
        code="N-2026-0001",
        status=status,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=USER,
        co_author_ids=[],
        title=title,
        created_at=NOW,
        updated_at=NOW,
        finalized_at=NOW if status is NoteStatus.FINALIZED else None,
        cancelled_at=None,
        visibility="private",
        shared_with_ids=[],
    )


class _Store:
    """The link table, in memory."""

    def __init__(self, note: repo.NoteRow) -> None:
        self.note = note
        self.links: list[repo.ShareLinkRow] = []
        self.revoked: list[UUID] = []


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import notes_sharing as router_mod

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    provider = MockProvider()

    class _Caps:
        blocked = False

        async def check(self, **kwargs):  # noqa: ANN003
            if self.blocked:
                from fastapi import HTTPException

                raise HTTPException(
                    429,
                    detail={"code": "share_mail_cap", "scope": "tenant"},
                    headers={"Retry-After": "60"},
                )

    caps = _Caps()
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            email_provider=provider,
            share_mail_caps=caps,
            redis=object(),
        )
    )
    monkeypatch.setattr(settings, "app_base_url", "https://app.notes-ai.test")
    monkeypatch.setattr(settings, "api_public_base_url", "https://api.notes-ai.test")
    monkeypatch.setattr(settings, "product_brand_name", "Klarnote")

    async def _branding(conn, *, tenant_id):  # noqa: ANN001
        return TenantBranding(
            tenant_id=str(tenant_id), display_name="Acme Consulting", contact_email="hello@acme.com"
        )

    monkeypatch.setattr(router_mod, "load_tenant_branding", _branding)

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    store = _Store(_note(title="SENTINEL-TITLE-XYZ"))
    store.suppressed: set[bytes] = set()  # type: ignore[attr-defined]

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return store.note if note_id == NOTE else None

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        return [
            SimpleNamespace(sub=USER, email="anna@acme.com", display_name="Anna Koval")
            for s in subs
            if s == USER
        ]

    async def _fetch_link(conn, *, link_id):  # noqa: ANN001
        return next((x for x in store.links if x.id == link_id), None)

    async def _record_send(conn, *, link_id, status, error_class=""):  # noqa: ANN001
        for x in store.links:
            if x.id == link_id:
                x.delivery_status = status
                x.send_count += 1
                x.last_send_error = error_class
                if status == "sent":
                    x.sent_at = NOW
                return x
        return None

    async def _is_suppressed(conn, *, email_hash):  # noqa: ANN001
        return email_hash in store.suppressed  # type: ignore[attr-defined]

    async def _list_links(conn, *, note_id):  # noqa: ANN001
        return [link for link in store.links if link.id not in store.revoked]

    async def _fetch_public(conn, *, note_id):  # noqa: ANN001
        return next(
            (x for x in store.links if x.kind == "public" and x.id not in store.revoked), None
        )

    async def _find_by_email(conn, *, note_id, recipient_email):  # noqa: ANN001
        return next(
            (
                link
                for link in store.links
                if link.id not in store.revoked and link.recipient_email == recipient_email
            ),
            None,
        )

    async def _create(conn, **kw):  # noqa: ANN001, ANN003
        link = repo.ShareLinkRow(
            id=kw["link_id"],
            note_id=kw["note_id"],
            created_by=kw["created_by"],
            created_at=NOW,
            expires_at=kw["expires_at"],
            last_viewed_at=None,
            view_count=0,
            kind=kw.get("kind", "public"),
            label=kw.get("label", ""),
            recipient_email=kw.get("recipient_email"),
            draft_acknowledged=kw.get("draft_acknowledged", False),
            ref_code=kw.get("ref_code"),
        )
        store.links.insert(0, link)
        return link

    async def _revoke_one(conn, *, note_id, link_id, actor_sub):  # noqa: ANN001
        hit = next((x for x in store.links if x.id == link_id and x.note_id == note_id), None)
        if hit is None or hit.id in store.revoked:
            return False
        store.revoked.append(hit.id)
        return True

    async def _revoke_all(conn, *, note_id, actor_sub):  # noqa: ANN001
        live = [x.id for x in store.links if x.id not in store.revoked]
        store.revoked.extend(live)
        return len(live)

    for name, fn in {
        "fetch_note": _fetch_note,
        "fetch_members": _fetch_members,
        "fetch_share_link": _fetch_link,
        "record_send_outcome": _record_send,
        "is_share_mail_suppressed": _is_suppressed,
        "list_live_share_links": _list_links,
        "fetch_live_share_link": _fetch_public,
        "find_live_recipient_link": _find_by_email,
        "create_share_link": _create,
        "revoke_share_link": _revoke_one,
        "revoke_share_links": _revoke_all,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    async def _no_counts(conn, *, note_id):  # noqa: ANN001
        return {}

    monkeypatch.setattr(items_repo, "live_response_counts_by_link", _no_counts)

    policy_box = {"policy": sharing_policy.SharingPolicy(), "plan": "free"}

    async def _load_policy(conn, *, tenant_id):  # noqa: ANN001
        return policy_box["policy"], policy_box["plan"]

    monkeypatch.setattr(sharing_policy, "load_policy", _load_policy)

    app = create_app()
    app.dependency_overrides[deps.current_user] = lambda: _claims()
    c = TestClient(app)
    c.store = store  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.app_ = app  # type: ignore[attr-defined]
    c.provider = provider  # type: ignore[attr-defined]
    c.caps = caps  # type: ignore[attr-defined]
    c.policy_box = policy_box  # type: ignore[attr-defined]
    return c


def _create(client: TestClient, **body):  # noqa: ANN003
    return client.post(f"/v1/notes/{NOTE}/links", json={"label": "Tom @ Client", **body})


# ── any live note can be shared (0042) ───────────────────────────────


def test_draft_note_is_shared_without_ceremony(client: TestClient) -> None:
    client.store.note = _note(NoteStatus.DRAFT)
    r = _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "recipient"
    assert body["path"] == f"/s/{body['token']}"
    assert body["expires_at"] is not None
    assert len(body["ref_code"]) == 12
    assert "draft_acknowledged" not in body


def test_unknown_fields_are_refused(client: TestClient) -> None:
    assert _create(client, draft_acknowledged=True).status_code == 422


# ── many links, one per recipient ────────────────────────────────────


def test_two_recipients_get_two_live_links(client: TestClient) -> None:
    a = _create(client, label="Tom", recipient_email="tom@client.com").json()
    b = _create(client, label="Ana", recipient_email="ana@client.com").json()
    assert a["id"] != b["id"]
    assert a["token"] != b["token"]
    assert a["ref_code"] != b["ref_code"]

    listed = client.get(f"/v1/notes/{NOTE}/links").json()
    assert [link["label"] for link in listed] == ["Ana", "Tom"]

    sharing = client.get(f"/v1/notes/{NOTE}/sharing").json()
    assert len(sharing["links"]) == 2
    assert sharing["public_link"] is None


def test_same_address_twice_returns_the_existing_link(client: TestClient) -> None:
    first = _create(client, recipient_email="Tom@Client.com")
    again = _create(client, recipient_email="tom@client.com ")
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert first.json()["recipient_email"] == "tom@client.com"


def test_revoking_one_leaves_the_other_working(client: TestClient) -> None:
    a = _create(client, label="Tom").json()
    b = _create(client, label="Ana").json()
    r = client.delete(f"/v1/notes/{NOTE}/links/{a['id']}")
    assert r.status_code == 204
    listed = client.get(f"/v1/notes/{NOTE}/links").json()
    assert [link["id"] for link in listed] == [b["id"]]
    # A second revoke of the same link is a 404, not a silent no-op.
    assert client.delete(f"/v1/notes/{NOTE}/links/{a['id']}").status_code == 404


def test_revoke_all_clears_every_link(client: TestClient) -> None:
    _create(client, label="Tom")
    _create(client, label="Ana")
    assert client.delete(f"/v1/notes/{NOTE}/links").status_code == 204
    assert client.get(f"/v1/notes/{NOTE}/links").json() == []


def test_public_link_still_unique_and_separate(client: TestClient) -> None:
    _create(client, label="Tom")
    first = client.post(f"/v1/notes/{NOTE}/public-link").json()
    second = client.post(f"/v1/notes/{NOTE}/public-link").json()
    assert first["public_link"]["id"] == second["public_link"]["id"]
    assert first["public_link"]["kind"] == "public"
    assert len(second["links"]) == 2


# ── who may ──────────────────────────────────────────────────────────


def test_outsider_in_the_tenant_cannot_see_or_touch_links(client: TestClient) -> None:
    from note_service import deps

    link = _create(client, label="Tom").json()
    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(sub=OTHER)
    assert _create(client, label="Mine").status_code == 404
    assert client.get(f"/v1/notes/{NOTE}/links").status_code == 404
    assert client.delete(f"/v1/notes/{NOTE}/links/{link['id']}").status_code == 404
    assert client.delete(f"/v1/notes/{NOTE}/links").status_code == 404


def test_shared_with_member_reads_but_cannot_manage(client: TestClient) -> None:
    from note_service import deps

    _create(client, label="Tom")
    client.store.note = _note()
    client.store.note.shared_with_ids = [OTHER]
    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(sub=OTHER)
    # May see the sheet, but tokens are for managers only.
    sharing = client.get(f"/v1/notes/{NOTE}/sharing").json()
    assert sharing["can_manage"] is False
    assert sharing["links"] == []
    assert _create(client, label="Mine").status_code == 403


# ── audit ────────────────────────────────────────────────────────────


def test_audit_carries_kind_and_flags_but_no_address_or_token(client: TestClient) -> None:
    body = _create(client, recipient_email="tom@client.com").json()
    created = [c for c in client.audit if c["kind"] == "note.link_created"]
    assert len(created) == 1
    payload = created[0]["payload"]
    assert payload["kind"] == "recipient"
    assert payload["has_recipient_email"] is True
    assert payload["link_id"] == body["id"]
    blob = repr(client.audit)
    assert "tom@client.com" not in blob
    assert body["token"] not in blob
    assert body["ref_code"] not in blob


# ── Sprint 22: the product sends the link ────────────────────────────


def test_send_mails_the_link_without_the_note(client: TestClient) -> None:
    link = _create(client, label="Tom @ Client", recipient_email="tom@client.com").json()
    r = client.post(
        f"/v1/notes/{NOTE}/links/{link['id']}/send", json={"personal_message": "See you Friday"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery_status"] == "sent"
    assert body["send_count"] == 1
    assert body["sent_at"] is not None

    (mail,) = client.provider.sent
    assert mail.to_address == "tom@client.com"
    assert mail.reply_to == "anna@acme.com"
    text = mail.text_body + mail.html_body
    assert f"https://app.notes-ai.test/s/{link['token']}" in text
    assert "Anna Koval" in text
    assert "Acme Consulting" in text
    assert "Meeting summary generated by Klarnote" in text
    assert "https://api.notes-ai.test/v1/shared/unsubscribe/" in text
    assert "See you Friday" in text
    assert "SENTINEL-TITLE-XYZ" not in text
    assert "SENTINEL-TITLE-XYZ" not in mail.subject

    sent = [c for c in client.audit if c["kind"] == "note.link_sent"]
    assert sent[0]["payload"] == {"link_id": link["id"], "resend": False, "outcome": "sent"}
    assert "tom@client.com" not in repr(client.audit)


def test_create_and_send_in_one_call(client: TestClient) -> None:
    r = _create(client, label="Tom", recipient_email="tom@client.com", send=True, lang="de")
    assert r.status_code == 201
    assert r.json()["delivery_status"] == "sent"
    assert len(client.provider.sent) == 1
    assert "Klarnote" in client.provider.sent[0].text_body


def test_send_needs_an_address_and_a_recipient_link(client: TestClient) -> None:
    no_email = _create(client, label="Tom").json()
    r = client.post(f"/v1/notes/{NOTE}/links/{no_email['id']}/send", json={})
    assert r.status_code == 422
    assert r.json()["code"] == "no_recipient_email"
    public = client.post(f"/v1/notes/{NOTE}/public-link").json()["public_link"]
    assert client.post(f"/v1/notes/{NOTE}/links/{public['id']}/send", json={}).status_code == 422
    assert client.provider.sent == []


def test_an_opted_out_recipient_is_not_mailed(client: TestClient) -> None:
    from note_service.domain.recipient_mail import email_hash

    client.store.suppressed.add(email_hash("Tom@Client.com"))
    link = _create(client, label="Tom", recipient_email="tom@client.com").json()
    r = client.post(f"/v1/notes/{NOTE}/links/{link['id']}/send", json={})
    assert r.status_code == 409
    assert r.json()["code"] == "recipient_opted_out"
    assert client.provider.sent == []
    listed = client.get(f"/v1/notes/{NOTE}/links").json()
    assert listed[0]["delivery_status"] == "suppressed"


def test_caps_answer_429(client: TestClient) -> None:
    link = _create(client, label="Tom", recipient_email="tom@client.com").json()
    client.caps.blocked = True
    r = client.post(f"/v1/notes/{NOTE}/links/{link['id']}/send", json={})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    assert client.provider.sent == []


def test_a_failed_relay_is_recorded_as_a_class_name(client: TestClient) -> None:
    from note_service.adapters.email import EmailDeliveryError

    async def _boom(message):  # noqa: ANN001
        raise EmailDeliveryError("relay said no")

    client.provider.send = _boom  # type: ignore[method-assign]
    link = _create(client, label="Tom", recipient_email="tom@client.com").json()
    r = client.post(f"/v1/notes/{NOTE}/links/{link['id']}/send", json={})
    assert r.status_code == 200
    assert r.json()["delivery_status"] == "failed"
    assert r.json()["last_send_error"] == "EmailDeliveryError"
    again = client.post(f"/v1/notes/{NOTE}/links/{link['id']}/send", json={})
    sent = [c["payload"]["resend"] for c in client.audit if c["kind"] == "note.link_sent"]
    assert sent == [False, True]
    assert again.status_code == 200


def test_unsubscribe_token_round_trips_and_rejects_forgery() -> None:
    from uuid import uuid4

    from note_service.domain import recipient_mail

    link_id = uuid4()
    token = recipient_mail.unsubscribe_token(link_id)
    assert "@" not in token and str(link_id) not in token
    assert recipient_mail.verify_unsubscribe_token(token) == link_id
    payload, _, sig = token.partition(".")
    assert recipient_mail.verify_unsubscribe_token(f"{payload}.{'0' * len(sig)}") is None
    assert recipient_mail.verify_unsubscribe_token("garbage") is None


# ── Sprint 23: the workspace's policy ────────────────────────────────


def test_policy_can_switch_external_links_off(client: TestClient) -> None:
    client.policy_box["policy"] = sharing_policy.SharingPolicy(external_links_enabled=False)
    r = _create(client, label="Tom")
    assert r.status_code == 403
    assert r.json()["code"] == "external_sharing_disabled"
    assert (
        client.get(f"/v1/notes/{NOTE}/sharing").json()["constraints"]["external_links_enabled"]
        is False
    )


def test_policy_can_switch_public_links_off(client: TestClient) -> None:
    client.policy_box["policy"] = sharing_policy.SharingPolicy(public_links_enabled=False)
    r = client.post(f"/v1/notes/{NOTE}/public-link")
    assert r.status_code == 403
    assert r.json()["code"] == "public_links_disabled"


def test_max_link_days_clips_instead_of_refusing(client: TestClient) -> None:
    client.policy_box["policy"] = sharing_policy.SharingPolicy(max_link_days=60)
    body = _create(client, label="Tom", expires_in_days=90).json()
    from datetime import datetime, timedelta

    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=59) < expires - datetime.now(expires.tzinfo) <= timedelta(days=60)


def test_product_email_policy_blocks_sending(client: TestClient) -> None:
    link = _create(client, label="Tom", recipient_email="tom@client.com").json()
    client.policy_box["policy"] = sharing_policy.SharingPolicy(product_email_enabled=False)
    r = client.post(f"/v1/notes/{NOTE}/links/{link['id']}/send", json={})
    assert r.status_code == 403
    assert r.json()["code"] == "product_email_disabled"
    assert client.provider.sent == []


def test_deployment_flag_beats_the_workspace(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "external_sharing_enabled", False)
    assert _create(client, label="Tom").status_code == 403
    c = client.get("/v1/notes/sharing/constraints").json()
    assert c == {**c, "external_links_enabled": False, "public_links_enabled": False}
