"""Google Calendar client: event normalisation and the HTTP calls (0019).

The transport is ``httpx.MockTransport``; nothing leaves the process.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from note_service.domain.google_calendar import (
    AUTH_ENDPOINT,
    CalendarInfo,
    GoogleCalendarClient,
    GoogleError,
    NeedsReauthError,
    normalize_event,
)

CAL = CalendarInfo(id="primary@x.com", name="Work", color="#ff0000", primary=True, selected=True)


# ── normalize_event ──


def test_timed_event() -> None:
    raw = {
        "id": "e1",
        "iCalUID": "uid-1",
        "summary": "  Weekly sync ",
        "start": {"dateTime": "2026-09-02T09:00:00+02:00"},
        "end": {"dateTime": "2026-09-02T09:30:00+02:00"},
        "hangoutLink": "https://meet.google.com/abc",
        "location": "Room 4",
        "htmlLink": "https://calendar.google.com/e1",
        "organizer": {"email": "boss@x.com"},
        "attendees": [
            {"email": "me@x.com", "self": True, "responseStatus": "accepted"},
            {"email": "boss@x.com", "displayName": "Boss"},
            {"email": "room@x.com", "resource": True},
        ],
    }
    ev = normalize_event(raw, CAL)
    assert ev is not None
    assert ev.title == "Weekly sync"
    assert ev.start == datetime(2026, 9, 2, 7, 0, tzinfo=UTC)
    assert ev.end == datetime(2026, 9, 2, 7, 30, tzinfo=UTC)
    assert not ev.all_day
    assert ev.meeting_url == "https://meet.google.com/abc"
    assert ev.location == "Room 4"
    assert ev.attendee_count == 2  # the room is not a person
    assert ev.attendees == ("me@x.com", "Boss")
    assert ev.organizer == "boss@x.com"
    assert ev.response_status == "accepted"
    assert ev.calendar_name == "Work"
    assert ev.color == "#ff0000"
    assert ev.ical_uid == "uid-1"


def test_all_day_event() -> None:
    raw = {
        "id": "e2",
        "summary": "Offsite",
        "start": {"date": "2026-09-03"},
        "end": {"date": "2026-09-04"},
    }
    ev = normalize_event(raw, CAL)
    assert ev is not None
    assert ev.all_day
    assert ev.start == datetime(2026, 9, 3, tzinfo=UTC)
    assert ev.end == datetime(2026, 9, 4, tzinfo=UTC)


def test_untitled_gets_placeholder() -> None:
    ev = normalize_event({"id": "e", "start": {"dateTime": "2026-09-02T09:00:00Z"}}, CAL)
    assert ev is not None
    assert ev.title == "(No title)"
    assert ev.end == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)  # 1h default


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "c", "status": "cancelled", "start": {"dateTime": "2026-09-02T09:00:00Z"}},
        {
            "id": "d",
            "start": {"dateTime": "2026-09-02T09:00:00Z"},
            "attendees": [{"self": True, "responseStatus": "declined"}],
        },
        {"id": "n", "summary": "no start"},
        {"id": "b", "start": {"dateTime": "not a date"}},
    ],
)
def test_skipped_events(raw: dict[str, Any]) -> None:
    assert normalize_event(raw, CAL) is None


def test_meeting_url_from_conference_data_and_text() -> None:
    conf = {
        "id": "x",
        "start": {"dateTime": "2026-09-02T09:00:00Z"},
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+1"},
                {"entryPointType": "video", "uri": "https://meet.google.com/xyz"},
            ]
        },
    }
    assert normalize_event(conf, CAL).meeting_url == "https://meet.google.com/xyz"  # type: ignore[union-attr]
    zoom = {
        "id": "z",
        "start": {"dateTime": "2026-09-02T09:00:00Z"},
        "description": "Join: https://us02web.zoom.us/j/123?pwd=abc. See you",
    }
    assert normalize_event(zoom, CAL).meeting_url == "https://us02web.zoom.us/j/123?pwd=abc"  # type: ignore[union-attr]
    plain = {"id": "p", "start": {"dateTime": "2026-09-02T09:00:00Z"}, "location": "Café"}
    assert normalize_event(plain, CAL).meeting_url is None  # type: ignore[union-attr]


# ── client ──


def _client(handler) -> GoogleCalendarClient:  # noqa: ANN001
    return GoogleCalendarClient(
        client_id="cid",
        client_secret="sec",
        redirect_uri="http://localhost:8006/v1/calendar/google/callback",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_configured_flag() -> None:
    assert not GoogleCalendarClient(client_id="", client_secret="", redirect_uri="x").configured
    assert not GoogleCalendarClient(client_id="a", client_secret="", redirect_uri="x").configured
    assert GoogleCalendarClient(client_id="a", client_secret="b", redirect_uri="x").configured


def test_authorize_url_shape() -> None:
    client = _client(lambda r: httpx.Response(500))
    url = client.authorize_url(state="st.sig", login_hint="me@x.com")
    assert url.startswith(AUTH_ENDPOINT + "?")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://localhost:8006/v1/calendar/google/callback"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["st.sig"]
    assert q["login_hint"] == ["me@x.com"]
    assert "calendar.readonly" in q["scope"][0]
    assert "calendar.events" not in q["scope"][0]  # read-only, never write


async def test_exchange_code_and_refresh() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen.append(form)
        if form["grant_type"] == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "access_token": "at1",
                    "refresh_token": "rt1",
                    "expires_in": 3600,
                    "scope": "openid email https://www.googleapis.com/auth/calendar.readonly",
                },
            )
        return httpx.Response(200, json={"access_token": "at2", "expires_in": 3599})

    client = _client(handler)
    first = await client.exchange_code("code123")
    assert first.access_token == "at1"
    assert first.refresh_token == "rt1"
    assert first.expires_at is not None
    assert "openid" in first.scopes
    assert seen[0]["code"] == "code123"
    assert seen[0]["client_secret"] == "sec"

    second = await client.refresh("rt1")
    assert second.access_token == "at2"
    assert second.refresh_token == "rt1"  # kept when Google omits it


async def test_refresh_invalid_grant_needs_reauth() -> None:
    client = _client(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(NeedsReauthError):
        await client.refresh("dead")


async def test_token_error_surfaces_description() -> None:
    client = _client(
        lambda r: httpx.Response(401, json={"error": "invalid_client", "error_description": "bad"})
    )
    with pytest.raises(GoogleError) as exc:
        await client.exchange_code("c")
    assert exc.value.code == "invalid_client"
    assert "bad" in str(exc.value)


async def test_list_calendars_and_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer at"
        path = request.url.path
        if path.endswith("/users/me/calendarList"):
            if request.url.params.get("pageToken") == "p2":
                return httpx.Response(200, json={"items": [{"id": "z@group", "summary": "Zebra"}]})
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "b@x", "summary": "Beta", "backgroundColor": "#00f"},
                        {"id": "me@x", "summary": "me@x", "primary": True},
                        {"id": "gone", "summary": "Gone", "deleted": True},
                    ],
                    "nextPageToken": "p2",
                },
            )
        if path.endswith("/calendars/me@x/events"):
            assert request.url.params["singleEvents"] == "true"
            assert request.url.params["timeMin"].endswith("Z")
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "1", "summary": "A", "start": {"dateTime": "2026-09-02T09:00:00Z"}},
                        {
                            "id": "2",
                            "status": "cancelled",
                            "start": {"dateTime": "2026-09-02T10:00:00Z"},
                        },
                    ]
                },
            )
        if path.endswith("/userinfo"):
            return httpx.Response(200, json={"email": "Me@X.com"})
        return httpx.Response(404, json={"error": {"message": "nope"}})

    client = _client(handler)
    cals = await client.list_calendars("at")
    assert [c.id for c in cals] == ["me@x", "b@x", "z@group"]  # primary first, then by name
    assert cals[1].color == "#00f"

    events = await client.list_events(
        "at",
        cals[0],
        time_min=datetime(2026, 9, 2, tzinfo=UTC),
        time_max=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert [e.id for e in events] == ["1"]
    assert events[0].calendar_name == "me@x"

    assert await client.account_email("at") == "me@x.com"

    with pytest.raises(GoogleError) as exc:
        await client.list_events(
            "at",
            cals[2],
            time_min=datetime(2026, 9, 2, tzinfo=UTC),
            time_max=datetime(2026, 9, 9, tzinfo=UTC),
        )
    assert exc.value.status == 404
    assert "nope" in str(exc.value)


async def test_unauthorized_is_a_google_error() -> None:
    client = _client(lambda r: httpx.Response(401, json={}))
    with pytest.raises(GoogleError) as exc:
        await client.list_calendars("stale")
    assert exc.value.code == "unauthorized"


async def test_revoke_never_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    await _client(handler).revoke("t")  # no exception


async def test_json_helper_tolerates_non_json() -> None:
    client = _client(lambda r: httpx.Response(500, content=b"<html>"))
    with pytest.raises(GoogleError) as exc:
        await client.exchange_code("c")
    assert exc.value.code == "http_500"
    assert json.loads('{"ok": 1}')  # keep json imported for symmetry with the module
