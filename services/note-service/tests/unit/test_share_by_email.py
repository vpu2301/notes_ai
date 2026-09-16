"""POST /v1/notes/{id}/share/email with the DB and the relay stubbed.

Mirrors ``test_spaces_router``: the real handler runs against an
overridden auth dependency, monkeypatched repository functions and the
in-memory mail provider.

What is worth asserting here is the split — a member is granted access
and sent into the app, a stranger gets the public link and nothing else —
and that one bad address does not swallow the rest of the batch. That
split is the whole reason the endpoint exists.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.adapters.email import EmailDeliveryError, EmailPermanentError, MockProvider
from note_service.domain import notes_repository as repo

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE = UUID("44444444-4444-4444-4444-444444444444")
COLLEAGUE = UUID("55555555-5555-5555-5555-555555555555")
LINK = UUID("66666666-6666-6666-6666-666666666666")
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

BASE = "https://app.notes-ai.test"


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


def _note(**over) -> repo.NoteRow:  # noqa: ANN003
    base: dict = {
        "id": NOTE,
        "tenant_id": TENANT,
        "code": "N-2026-0001",
        "status": repo.NoteStatus.DRAFT,
        "current_version_id": uuid4(),
        "current_version_number": 1,
        "primary_author_id": USER,
        "co_author_ids": [],
        "title": "Acme kickoff",
        "created_at": NOW,
        "updated_at": NOW,
        "finalized_at": None,
        "cancelled_at": None,
        "visibility": "private",
        "shared_with_ids": [],
    }
    base.update(over)
    return repo.NoteRow(**base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.config import settings
    from note_service.main import create_app
    from note_service.routers import notes_sharing as router_mod

    monkeypatch.setattr(settings, "app_base_url", BASE)

    audit_calls: list[dict] = []
    notified: list[UUID] = []
    provider = MockProvider()

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    class _NoLimit:
        async def check(self, *, user_id, cost):  # noqa: ANN001, ANN003
            return True, 0

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            redis=object(),
            email_provider=provider,
            share_email_rate_limiter=_NoLimit(),
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    async def _emit(*args, **kwargs):  # noqa: ANN002, ANN003
        notified.append(kwargs["primary_author_id"])

    monkeypatch.setattr(router_mod, "emit_note_event", _emit)

    state = {"note": _note(), "link": None, "links_created": 0}

    async def _fetch_note(conn, *, note_id):  # noqa: ANN001
        return state["note"] if note_id == NOTE else None

    async def _find_member(conn, *, email):  # noqa: ANN001
        if email.lower() == "colleague@acme.com":
            return SimpleNamespace(
                sub=COLLEAGUE, email="colleague@acme.com", display_name="Colleague"
            )
        return None

    async def _fetch_members(conn, *, subs):  # noqa: ANN001
        people = {
            USER: SimpleNamespace(sub=USER, email="anna@acme.com", display_name="Anna Koval"),
            COLLEAGUE: SimpleNamespace(
                sub=COLLEAGUE, email="colleague@acme.com", display_name="Colleague"
            ),
        }
        return [people[s] for s in subs if s in people]

    async def _add_shared(conn, *, note_id, user_sub):  # noqa: ANN001
        note = state["note"]
        state["note"] = _note(shared_with_ids=[*note.shared_with_ids, user_sub])

    async def _fetch_link(conn, *, note_id):  # noqa: ANN001
        return state["link"]

    async def _create_link(
        conn, *, link_id, tenant_id, note_id, token_hash, created_by, expires_at
    ):  # noqa: ANN001
        state["links_created"] += 1
        row = repo.ShareLinkRow(
            id=LINK,
            note_id=note_id,
            created_by=created_by,
            created_at=NOW,
            expires_at=expires_at,
            last_viewed_at=None,
            view_count=0,
        )
        state["link"] = row
        return row

    for name, fn in {
        "fetch_note": _fetch_note,
        "find_member_by_email": _find_member,
        "fetch_members": _fetch_members,
        "add_shared_with": _add_shared,
        "fetch_live_share_link": _fetch_link,
        "create_share_link": _create_link,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    c = TestClient(app)
    c.provider = provider  # type: ignore[attr-defined]
    c.audit = audit_calls  # type: ignore[attr-defined]
    c.notified = notified  # type: ignore[attr-defined]
    c.state_ = state  # type: ignore[attr-defined]
    return c


def _send(client: TestClient, **body) -> object:  # noqa: ANN003
    return client.post(f"/v1/notes/{NOTE}/share/email", json=body)


def test_member_is_granted_access_and_sent_an_app_link(client: TestClient) -> None:
    r = _send(client, recipients=["colleague@acme.com"], message="Recap inside.")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["results"] == [
        {"email": "colleague@acme.com", "access": "member", "status": "sent"}
    ]
    # No public link was minted: the note did not need one.
    assert body["public_link_created"] is False
    assert client.state_["links_created"] == 0
    assert COLLEAGUE in client.state_["note"].shared_with_ids
    # They still get the ordinary content-free "shared with you" ping.
    assert client.notified == [COLLEAGUE]

    (mail,) = client.provider.sent
    assert mail.to_address == "colleague@acme.com"
    assert "Acme kickoff" in mail.subject
    assert f"{BASE}/notes/{NOTE}" in mail.text_body
    assert f"{BASE}/notes/{NOTE}" in mail.html_body
    # The sharer's own words, and a reply that reaches them.
    assert "Recap inside." in mail.text_body
    assert mail.reply_to == "anna@acme.com"


def test_stranger_gets_a_public_link_minted_for_them(client: TestClient) -> None:
    r = _send(client, recipients=["outsider@example.com"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["results"][0]["access"] == "link"
    assert body["public_link_created"] is True
    assert client.state_["links_created"] == 1
    assert body["sharing"]["public_link"]["path"].startswith("/s/")

    (mail,) = client.provider.sent
    token = body["sharing"]["public_link"]["token"]
    assert f"{BASE}/s/{token}" in mail.text_body
    # The mail says what a public link means, rather than implying an
    # account is involved.
    assert "no account needed" in mail.text_body.lower()
    assert client.notified == []


def test_one_batch_mints_at_most_one_link(client: TestClient) -> None:
    r = _send(client, recipients=["a@example.com", "b@example.com", "colleague@acme.com"])
    assert r.status_code == 200, r.text
    assert client.state_["links_created"] == 1
    assert [x["access"] for x in r.json()["results"]] == ["link", "link", "member"]
    assert len(client.provider.sent) == 3


def test_a_dead_address_does_not_swallow_the_rest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_send = client.provider.send

    async def _send_one(message):  # noqa: ANN001
        if message.to_address == "bounce@example.com":
            raise EmailPermanentError("smtp permanent 550")
        if message.to_address == "flaky@example.com":
            raise EmailDeliveryError("connection reset")
        return await real_send(message)

    monkeypatch.setattr(client.provider, "send", _send_one)

    r = _send(
        client,
        recipients=["bounce@example.com", "flaky@example.com", "ok@example.com"],
    )
    assert r.status_code == 200, r.text
    assert {x["email"]: x["status"] for x in r.json()["results"]} == {
        "bounce@example.com": "rejected",
        "flaky@example.com": "failed",
        "ok@example.com": "sent",
    }
    assert [m.to_address for m in client.provider.sent] == ["ok@example.com"]


def test_addresses_are_deduped_case_insensitively(client: TestClient) -> None:
    r = _send(client, recipients=["Same@Example.com", "same@example.com"])
    assert r.status_code == 200, r.text
    assert len(r.json()["results"]) == 1
    assert len(client.provider.sent) == 1


def test_a_nonsense_address_is_refused_before_any_mail_goes_out(client: TestClient) -> None:
    r = _send(client, recipients=["colleague@acme.com", "not an address"])
    assert r.status_code == 422
    assert client.provider.sent == []


def test_the_recipient_cap_is_enforced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from note_service.config import settings

    monkeypatch.setattr(settings, "share_email_max_recipients", 2)
    r = _send(client, recipients=[f"p{i}@example.com" for i in range(3)])
    assert r.status_code == 422
    assert client.provider.sent == []


def test_the_hourly_cap_answers_429_with_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from note_service import deps

    class _Exhausted:
        async def check(self, *, user_id, cost):  # noqa: ANN001, ANN003
            return False, 1234

    monkeypatch.setattr(deps.get_state(), "share_email_rate_limiter", _Exhausted())
    r = _send(client, recipients=["someone@example.com"])
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "1234"
    assert client.provider.sent == []


def test_the_audit_entry_counts_recipients_and_never_names_them(client: TestClient) -> None:
    _send(client, recipients=["colleague@acme.com", "outsider@example.com"], message="hi")
    emailed = [c for c in client.audit if c["kind"] == "note.link_emailed"]
    assert len(emailed) == 1
    payload = emailed[0]["payload"]
    assert payload == {
        "recipients": 2,
        "members": 1,
        "sent": 2,
        "failed": 0,
        "had_message": True,
    }
    assert "example.com" not in str(client.audit)


# ── The MIME document ────────────────────────────────────────────────
# A share mail can be handed to the relay, accepted with a clean 250 and
# still never reach the recipient's inbox. ``Date`` is a REQUIRED header
# (RFC 5322 §3.6) and a message without it — or without ``Message-ID`` —
# is scored as suspicious by every major provider, so these assertions
# are about delivery, not tidiness.


def test_the_mime_document_carries_date_and_message_id() -> None:
    from note_service.adapters import email as email_mod

    mime = email_mod.build_mime(
        email_mod.OutboundEmail(
            to_address="outsider@example.com",
            subject="Anna shared a note with you",
            text_body="plain",
            html_body="<p>rich</p>",
            reply_to="anna@acme.com",
        ),
        from_address="notes@notes-ai.test",
        from_name="Notes AI",
    )

    assert mime["Date"]
    assert mime["Message-ID"].endswith("@notes-ai.test>")
    assert mime["From"] == "Notes AI <notes@notes-ai.test>"
    assert mime["Reply-To"] == "anna@acme.com"
    # Text first, HTML second: a client that reads the parts in order
    # shows the sharer's words, not the markup around them.
    assert mime.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in mime.iter_parts()] == [
        "text/plain",
        "text/html",
    ]


def test_reply_to_falls_back_to_the_configured_mailbox() -> None:
    """A sharer with no address on file must still leave a reply path."""
    from note_service.adapters import email as email_mod

    mime = email_mod.build_mime(
        email_mod.OutboundEmail(
            to_address="outsider@example.com",
            subject="A colleague shared a note with you",
            text_body="plain",
            reply_to="",
        ),
        from_address="notes@notes-ai.test",
        from_name="Notes AI",
        reply_to_fallback="notes@notes-ai.test",
    )

    assert mime["Reply-To"] == "notes@notes-ai.test"
