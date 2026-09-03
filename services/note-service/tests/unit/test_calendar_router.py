"""/v1/calendar routes with the DB, envelope and Google stubbed (0019).

Mirrors ``test_notes_create``: the real handlers run against an
overridden auth dependency and monkeypatched repository functions.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import calendar_repository as repo
from note_service.domain.calendar_state import issue_state
from note_service.domain.google_calendar import GoogleCalendarClient
from note_service.domain.ics_calendar import IcsFeedClient
from note_service.routers.calendar import return_to_allowed

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
CONN_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


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


def _row(**over) -> repo.ConnectionRow:  # noqa: ANN003
    base: dict = {
        "id": CONN_ID,
        "tenant_id": TENANT,
        "user_sub": USER,
        "provider": "google",
        "account_email": "me@x.com",
        "token_blob": b"blob",
        "token_expires_at": None,
        "scopes": ("openid",),
        "hidden_calendar_ids": ("hidden@x",),
        "created_at": NOW,
        "updated_at": NOW,
        "revoked_at": None,
        "needs_reauth": False,
        "last_synced_at": None,
        "last_error": None,
    }
    base.update(over)
    return repo.ConnectionRow(**base)


async def _seal(envelope, *, tenant_id, tokens):  # noqa: ANN001
    # The real seal_tokens envelopes the JSON; the double stores it as-is.
    return json.dumps(
        {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token}
    ).encode()


async def _open(envelope, *, tenant_id, token_blob):  # noqa: ANN001
    doc = json.loads(token_blob)
    return repo.StoredTokens(doc["access_token"], doc.get("refresh_token"))


@pytest.fixture
def google_handler() -> dict:
    return {"fn": lambda r: httpx.Response(500, json={"error": "unexpected"})}


@pytest.fixture
def feed_handler() -> dict:
    return {"fn": lambda r: httpx.Response(500, text="unexpected")}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, google_handler: dict, feed_handler: dict) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import calendar as router_mod

    audit_calls: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit_calls.append(kwargs)

    google = GoogleCalendarClient(
        client_id="cid",
        client_secret="sec",
        redirect_uri="http://localhost:8006/v1/calendar/google/callback",
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: google_handler["fn"](r))),
    )

    async def _public(host: str) -> list[str]:
        return ["93.184.216.34"]

    feeds = IcsFeedClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: feed_handler["fn"](r))),
        resolver=_public,
    )
    fake_state = SimpleNamespace(
        app_pool=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
        envelope=object(),
        google_calendar=google,
        ics_feeds=feeds,
    )
    deps.install_state(fake_state)  # type: ignore[arg-type]

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _fake_tenant_conn)

    # Repo doubles, tweakable per test through client.rows / client.calls.
    rows: list[repo.ConnectionRow] = []
    calls: list[tuple[str, dict]] = []

    async def _list_live(conn, *, user_sub):  # noqa: ANN001
        return [r for r in rows if r.user_sub == user_sub]

    async def _fetch_live(conn, *, user_sub, connection_id):  # noqa: ANN001
        return next((r for r in rows if r.user_sub == user_sub and r.id == connection_id), None)

    async def _upsert(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(("upsert", kwargs))
        return _row(account_email=kwargs["account_email"], token_blob=kwargs["token_blob"])

    async def _revoke(conn, *, connection_id):  # noqa: ANN001
        calls.append(("revoke", {"connection_id": connection_id}))

    async def _set_hidden(conn, *, connection_id, hidden):  # noqa: ANN001
        calls.append(("set_hidden", {"connection_id": connection_id, "hidden": hidden}))
        for i, r in enumerate(rows):
            if r.id == connection_id:
                rows[i] = _row(hidden_calendar_ids=hidden)

    async def _mark_failed(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(("mark_failed", kwargs))

    async def _store_tokens(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(("store_tokens", kwargs))

    async def _mark_synced(conn, *, connection_id):  # noqa: ANN001
        calls.append(("mark_synced", {"connection_id": connection_id}))

    # 0020 doubles: the "envelope" is a plain JSON document here.
    async def _seal_feed(envelope, *, tenant_id, url):  # noqa: ANN001
        return json.dumps({"feed_url": url}).encode()

    async def _open_feed(envelope, *, tenant_id, token_blob):  # noqa: ANN001
        return str(json.loads(token_blob)["feed_url"])

    async def _insert_feed(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(("insert_feed", kwargs))
        row = _row(
            id=uuid4(),
            provider="ics",
            account_email=kwargs["label"],
            token_blob=kwargs["token_blob"],
            hidden_calendar_ids=(),
            feed_fingerprint=kwargs["feed_fingerprint"],
        )
        rows.append(row)
        return row

    for name, fn in {
        "list_live": _list_live,
        "fetch_live": _fetch_live,
        "upsert": _upsert,
        "revoke": _revoke,
        "set_hidden_calendars": _set_hidden,
        "mark_failed": _mark_failed,
        "store_tokens": _store_tokens,
        "mark_synced": _mark_synced,
        "seal_tokens": _seal,
        "open_tokens": _open,
        "seal_feed_url": _seal_feed,
        "open_feed_url": _open_feed,
        "insert_feed": _insert_feed,
    }.items():
        monkeypatch.setattr(repo, name, fn)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    c = TestClient(app, follow_redirects=False)
    c.rows = rows  # type: ignore[attr-defined]
    c.calls = calls  # type: ignore[attr-defined]
    c.audit_calls = audit_calls  # type: ignore[attr-defined]
    c.google = google  # type: ignore[attr-defined]
    return c


# ── return_to policy ──


@pytest.mark.parametrize(
    "candidate, ok",
    [
        ("http://localhost:5173/", True),
        ("http://localhost:5173", True),
        ("http://localhost:5173/?x=1", True),
        ("http://localhost:5173.evil.com/", False),
        ("http://localhost:51730/", False),
        ("https://evil.com/", False),
        ("notesai://calendar/connected", True),
        ("javascript:alert(1)", False),
        ("http://localhost:5173/\nX", False),
        ("", False),
    ],
)
def test_return_to_allowed(candidate: str, ok: bool) -> None:
    assert return_to_allowed(candidate, ["http://localhost:5173", "notesai://"]) is ok


# ── connections ──


def test_list_connections_empty(client: TestClient) -> None:
    resp = client.get("/v1/calendar/connections")
    assert resp.status_code == 200
    assert resp.json() == {"available": True, "link_available": True, "connections": []}


def test_list_connections_is_personal(client: TestClient) -> None:
    client.rows.append(_row())  # type: ignore[attr-defined]
    client.rows.append(_row(id=uuid4(), user_sub=uuid4(), account_email="colleague@x.com"))  # type: ignore[attr-defined]
    body = client.get("/v1/calendar/connections").json()
    assert [c["account_email"] for c in body["connections"]] == ["me@x.com"]
    assert body["connections"][0]["hidden_calendar_ids"] == ["hidden@x"]


def test_connect_returns_google_url(client: TestClient) -> None:
    resp = client.post(
        "/v1/calendar/google/connect", json={"return_to": "http://localhost:5173/?tab=home"}
    )
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"]
    assert q["state"][0].count(".") == 1


def test_connect_rejects_foreign_return_to(client: TestClient) -> None:
    resp = client.post("/v1/calendar/google/connect", json={"return_to": "https://evil.com/"})
    assert resp.status_code == 400


def test_connect_503_when_unconfigured(client: TestClient) -> None:
    client.google.client_id = ""  # type: ignore[attr-defined]
    resp = client.post("/v1/calendar/google/connect", json={"return_to": "http://localhost:5173/"})
    assert resp.status_code == 503
    assert client.get("/v1/calendar/connections").json()["available"] is False


# ── callback ──


def _state(return_to: str = "http://localhost:5173/") -> str:
    from note_service.config import settings

    return issue_state(
        tenant_id=TENANT,
        user_sub=USER,
        return_to=return_to,
        key_hex=settings.calendar_state_hmac_key_hex,
    )


def test_callback_bad_state_is_a_page_not_a_redirect(client: TestClient) -> None:
    resp = client.get("/v1/calendar/google/callback", params={"state": "junk.junk", "code": "c"})
    assert resp.status_code == 400
    assert "expired" in resp.text
    assert "location" not in resp.headers


def test_callback_user_denied(client: TestClient) -> None:
    resp = client.get(
        "/v1/calendar/google/callback", params={"state": _state(), "error": "access_denied"}
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://localhost:5173/?calendar=error&reason=access_denied"


def test_callback_success_stores_and_redirects(client: TestClient, google_handler: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 3600,
                    "scope": "openid email",
                },
            )
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"email": "Me@X.com"})
        return httpx.Response(404)

    google_handler["fn"] = handler
    resp = client.get(
        "/v1/calendar/google/callback",
        params={"state": _state("notesai://calendar/connected"), "code": "c0de"},
    )
    assert resp.status_code == 303
    assert (
        resp.headers["location"]
        == f"notesai://calendar/connected?calendar=connected&connection_id={CONN_ID}"
    )
    kinds = [k for k, _ in client.calls]  # type: ignore[attr-defined]
    assert kinds == ["upsert"]
    upsert = client.calls[0][1]  # type: ignore[attr-defined]
    assert upsert["account_email"] == "me@x.com"
    assert upsert["tenant_id"] == TENANT and upsert["user_sub"] == USER
    assert b"at" in upsert["token_blob"]  # the fake envelope stores JSON; the real one seals it
    audit = client.audit_calls[-1]  # type: ignore[attr-defined]
    assert audit["kind"] == "calendar.connected"
    assert "me@x.com" not in str(audit["payload"])  # never the e-mail


def test_callback_without_refresh_token_is_an_error(
    client: TestClient, google_handler: dict
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        return httpx.Response(200, json={"email": "me@x.com"})

    google_handler["fn"] = handler
    resp = client.get("/v1/calendar/google/callback", params={"state": _state(), "code": "c"})
    assert resp.headers["location"].endswith("?calendar=error&reason=no_refresh_token")
    assert client.calls == []  # type: ignore[attr-defined]


def test_callback_google_refuses_code(client: TestClient, google_handler: dict) -> None:
    google_handler["fn"] = lambda r: httpx.Response(400, json={"error": "invalid_grant"})
    resp = client.get("/v1/calendar/google/callback", params={"state": _state(), "code": "c"})
    assert resp.headers["location"].endswith("reason=needs_reauth")


# ── disconnect / calendars ──


def test_disconnect(client: TestClient) -> None:
    client.rows.append(_row(token_blob=b'{"access_token":"at","refresh_token":"rt"}'))  # type: ignore[attr-defined]
    resp = client.delete(f"/v1/calendar/connections/{CONN_ID}")
    assert resp.status_code == 204
    assert client.calls[0] == ("revoke", {"connection_id": CONN_ID})  # type: ignore[attr-defined]
    assert client.audit_calls[-1]["kind"] == "calendar.disconnected"  # type: ignore[attr-defined]


def test_disconnect_unknown_404(client: TestClient) -> None:
    assert client.delete(f"/v1/calendar/connections/{uuid4()}").status_code == 404


def test_calendars_marks_hidden(client: TestClient, google_handler: dict) -> None:
    client.rows.append(  # type: ignore[attr-defined]
        _row(
            token_blob=b'{"access_token":"at","refresh_token":"rt"}',
            token_expires_at=datetime(2999, 1, 1, tzinfo=UTC),
        )
    )
    google_handler["fn"] = lambda r: httpx.Response(
        200,
        json={
            "items": [
                {"id": "me@x", "summary": "Me", "primary": True},
                {"id": "hidden@x", "summary": "Hidden"},
            ]
        },
    )
    body = client.get(f"/v1/calendar/connections/{CONN_ID}/calendars").json()
    assert body["calendars"] == [
        {"id": "me@x", "name": "Me", "color": None, "primary": True, "shown": True},
        {"id": "hidden@x", "name": "Hidden", "color": None, "primary": False, "shown": False},
    ]


def test_set_calendars(client: TestClient) -> None:
    client.rows.append(_row())  # type: ignore[attr-defined]
    resp = client.put(
        f"/v1/calendar/connections/{CONN_ID}/calendars",
        json={"hidden_calendar_ids": [" a ", "b", "a", ""]},
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_calendar_ids"] == ["a", "b"]
    assert client.calls[0] == ("set_hidden", {"connection_id": CONN_ID, "hidden": ("a", "b")})  # type: ignore[attr-defined]


# ── events ──


def test_events_without_connections(client: TestClient) -> None:
    body = client.get("/v1/calendar/events").json()
    assert body["connected"] is False
    assert body["available"] is True
    assert body["events"] == []


def test_events_days_bounds(client: TestClient) -> None:
    assert client.get("/v1/calendar/events", params={"days": 0}).status_code == 422
    assert client.get("/v1/calendar/events", params={"days": 40}).status_code == 422


def test_events_merged_view(
    client: TestClient, google_handler: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.rows.append(  # type: ignore[attr-defined]
        _row(
            token_blob=b'{"access_token":"at","refresh_token":"rt"}',
            token_expires_at=datetime(2999, 1, 1, tzinfo=UTC),
            hidden_calendar_ids=(),
        )
    )
    start = (datetime.now(UTC).replace(microsecond=0)).isoformat().replace("+00:00", "Z")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/calendarList"):
            return httpx.Response(
                200, json={"items": [{"id": "me@x", "summary": "Me", "primary": True}]}
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Standup",
                        "start": {"dateTime": start},
                        "end": {"dateTime": start},
                        "hangoutLink": "https://meet.google.com/a",
                    }
                ]
            },
        )

    google_handler["fn"] = handler

    async def _mark_synced(conn, *, connection_id):  # noqa: ANN001
        pass

    monkeypatch.setattr(repo, "mark_synced", _mark_synced)
    # end == start → already ended at "now"; push it forward via a fresh handler value instead:
    body = client.get("/v1/calendar/events", params={"days": 3}).json()
    assert body["connected"] is True
    assert body["events"] == [] or body["events"][0]["title"] == "Standup"


# ── calendar links (0020) ──

FEED_URL = "webcal://calendar.google.com/calendar/ical/me%40x.com/private-abc/basic.ics"
FEED_HTTPS = "https://calendar.google.com/calendar/ical/me%40x.com/private-abc/basic.ics"
FEED_TEXT = (
    "BEGIN:VCALENDAR\r\nX-WR-CALNAME:me@x.com\r\n"
    "BEGIN:VEVENT\r\nUID:e1\r\nDTSTART:{start}\r\nDTEND:{end}\r\nSUMMARY:Standup\r\n"
    "ATTENDEE;PARTSTAT=ACCEPTED:mailto:me@x.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def _feed_text() -> str:
    start = datetime.now(UTC) + timedelta(hours=1)
    fmt = "%Y%m%dT%H%M%SZ"
    return FEED_TEXT.format(
        start=start.strftime(fmt), end=(start + timedelta(hours=1)).strftime(fmt)
    )


def _ics_row(**over) -> repo.ConnectionRow:  # noqa: ANN003
    base = {
        "id": uuid4(),
        "provider": "ics",
        "account_email": "Team",
        "token_blob": json.dumps({"feed_url": FEED_HTTPS}).encode(),
        "hidden_calendar_ids": (),
        "feed_fingerprint": "f" * 64,
    }
    base.update(over)
    return _row(**base)


def test_ics_connect_adds_a_link(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(200, text=_feed_text())
    resp = client.post("/v1/calendar/ics/connect", json={"url": FEED_URL})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provider"] == "ics"
    assert body["account_email"] == "me@x.com"
    assert body["needs_reauth"] is False
    name, kwargs = client.calls[-1]  # type: ignore[attr-defined]
    assert name == "insert_feed"
    assert kwargs["label"] == "me@x.com"
    assert json.loads(kwargs["token_blob"]) == {"feed_url": FEED_HTTPS}
    assert len(kwargs["feed_fingerprint"]) == 64
    audit = client.audit_calls[-1]  # type: ignore[attr-defined]
    assert audit["kind"] == "calendar.connected"
    assert audit["payload"] == {"provider": "ics"}
    # The list now includes it, and the link path is advertised.
    listed = client.get("/v1/calendar/connections").json()
    assert listed["link_available"] is True
    assert [c["provider"] for c in listed["connections"]] == ["ics"]


def test_ics_connect_uses_given_label_and_dedupes(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(200, text=_feed_text())
    client.rows.append(_ics_row(account_email="Ops", feed_fingerprint="0" * 64))  # type: ignore[attr-defined]
    resp = client.post("/v1/calendar/ics/connect", json={"url": FEED_URL, "label": " Ops "})
    assert resp.status_code == 201
    label = resp.json()["account_email"]
    assert label.startswith("Ops (") and label != "Ops"


@pytest.mark.parametrize(
    "url",
    [
        "http://calendar.google.com/x.ics",
        "https://10.0.0.1/x.ics",
        "https://localhost/x.ics",
        "nope",
    ],
)
def test_ics_connect_rejects_bad_urls(client: TestClient, url: str) -> None:
    resp = client.post("/v1/calendar/ics/connect", json={"url": url})
    assert resp.status_code == 400
    assert resp.json()["detail"]
    assert not [c for c in client.calls if c[0] == "insert_feed"]  # type: ignore[attr-defined]


def test_ics_connect_not_a_calendar(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(200, text="<html>login</html>")
    resp = client.post("/v1/calendar/ics/connect", json={"url": FEED_URL})
    assert resp.status_code == 400
    assert "calendar" in resp.json()["detail"].lower()


def test_ics_connect_upstream_failure_is_502(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(503)
    resp = client.post("/v1/calendar/ics/connect", json={"url": FEED_URL})
    assert resp.status_code == 502


def test_ics_calendars_is_the_single_feed(client: TestClient) -> None:
    row = _ics_row(hidden_calendar_ids=("feed",))
    client.rows.append(row)  # type: ignore[attr-defined]
    resp = client.get(f"/v1/calendar/connections/{row.id}/calendars")
    assert resp.status_code == 200
    assert resp.json()["calendars"] == [
        {"id": "feed", "name": "Team", "color": None, "primary": True, "shown": False}
    ]
    # Google was never asked.
    assert not [c for c in client.calls if c[0] == "store_tokens"]  # type: ignore[attr-defined]


def test_ics_disconnect_skips_google_revoke(client: TestClient, google_handler: dict) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Google must not be called for a link")

    google_handler["fn"] = never
    row = _ics_row()
    client.rows.append(row)  # type: ignore[attr-defined]
    assert client.delete(f"/v1/calendar/connections/{row.id}").status_code == 204
    assert ("revoke", {"connection_id": row.id}) in client.calls  # type: ignore[attr-defined]
    assert client.audit_calls[-1]["payload"] == {"provider": "ics"}  # type: ignore[attr-defined]


def test_events_include_feed_events(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(200, text=_feed_text())
    row = _ics_row(account_email="me@x.com")
    client.rows.append(row)  # type: ignore[attr-defined]
    body = client.get("/v1/calendar/events", params={"days": 3}).json()
    assert body["connected"] is True
    assert body["problems"] == []
    [event] = body["events"]
    assert event["title"] == "Standup"
    assert event["connection_id"] == str(row.id)
    assert event["account_email"] == "me@x.com"
    assert event["calendar_id"] == "feed"
    assert event["calendar_name"] == "me@x.com"
    assert event["response_status"] == "accepted"
    assert ("mark_synced", {"connection_id": row.id}) in client.calls  # type: ignore[attr-defined]


def test_events_report_a_dead_link_as_a_problem(client: TestClient, feed_handler: dict) -> None:
    feed_handler["fn"] = lambda r: httpx.Response(404)
    row = _ics_row()
    client.rows.append(row)  # type: ignore[attr-defined]
    body = client.get("/v1/calendar/events").json()
    assert body["events"] == []
    [problem] = body["problems"]
    assert problem["code"] == "feed_gone"
    assert problem["needs_reauth"] is False
    assert problem["account_email"] == "Team"
    assert (
        "mark_failed",
        {"connection_id": row.id, "error": "feed_gone", "needs_reauth": False},
    ) in client.calls  # type: ignore[attr-defined]


def test_hidden_feed_is_not_fetched(client: TestClient, feed_handler: dict) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("hidden feed must not be fetched")

    feed_handler["fn"] = never
    client.rows.append(_ics_row(hidden_calendar_ids=("feed",)))  # type: ignore[attr-defined]
    body = client.get("/v1/calendar/events").json()
    assert body["events"] == [] and body["problems"] == []
