"""Calendar links: URL policy, fetching, ICS parsing and expansion (0020)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from note_service.domain import ics_calendar as ics
from note_service.domain.google_calendar import CalendarInfo

CAL = CalendarInfo(id="feed", name="Work", color=None, primary=True, selected=True)
# The window every test expands into: Wed 2 Sep 2026 → +8 days.
TIME_MIN = datetime(2026, 9, 2, tzinfo=UTC)
TIME_MAX = TIME_MIN + timedelta(days=8)


def _feed(*events: str, name: str = "me@x.com", tz: str | None = "Europe/Kyiv") -> str:
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", f"X-WR-CALNAME:{name}"]
    if tz:
        head.append(f"X-WR-TIMEZONE:{tz}")
    body = "\r\n".join(head + list(events) + ["END:VCALENDAR"])
    return body + "\r\n"


def _vevent(*lines: str) -> str:
    return "\r\n".join(["BEGIN:VEVENT", *lines, "END:VEVENT"])


def _expand(text: str, **kw):  # noqa: ANN003, ANN202
    return ics.upcoming_events(
        ics.parse_feed(text), calendar=CAL, time_min=TIME_MIN, time_max=TIME_MAX, **kw
    )


# ── URL policy ──


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://calendar.google.com/calendar/ical/x/private-abc/basic.ics", None),
        (
            "webcal://p01-calendars.icloud.com/published/2/abc",
            "https://p01-calendars.icloud.com/published/2/abc",
        ),
        ("  https://example.com/cal.ics#frag ", "https://example.com/cal.ics"),
        ("https://example.com", "https://example.com/"),
    ],
)
def test_normalize_feed_url(raw: str, expected: str | None) -> None:
    assert ics.normalize_feed_url(raw) == (expected or raw.strip())


@pytest.mark.parametrize(
    "raw, code",
    [
        ("", "bad_url"),
        ("http://example.com/cal.ics", "bad_url"),
        ("ftp://example.com/cal.ics", "bad_url"),
        ("https://user:pw@example.com/cal.ics", "bad_url"),
        ("https://example.com/a b", "bad_url"),
        ("https://localhost/cal.ics", "private_host"),
        ("https://db.internal/cal.ics", "private_host"),
        ("https://printer.local/cal.ics", "private_host"),
        ("https://127.0.0.1/cal.ics", "private_host"),
        ("https://10.1.2.3/cal.ics", "private_host"),
        ("https://169.254.169.254/latest/meta-data", "private_host"),
        ("https://[::1]/cal.ics", "private_host"),
        ("https://[::ffff:10.0.0.1]/cal.ics", "private_host"),
    ],
)
def test_normalize_feed_url_rejects(raw: str, code: str) -> None:
    with pytest.raises(ics.FeedError) as info:
        ics.normalize_feed_url(raw)
    assert info.value.code == code


def test_fingerprint_is_stable_and_opaque() -> None:
    url = "https://example.com/cal.ics"
    assert ics.feed_fingerprint(url) == ics.feed_fingerprint(url)
    assert len(ics.feed_fingerprint(url)) == 64
    assert "example" not in ics.feed_fingerprint(url)


@pytest.mark.asyncio
async def test_assert_public_host_uses_resolver() -> None:
    async def private(host: str) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    async def public(host: str) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(ics.FeedError) as info:
        await ics.assert_public_host("https://example.com/", private)
    assert info.value.code == "private_host"
    await ics.assert_public_host("https://example.com/", public)


# ── Fetching ──


def _client(handler, resolver=None):  # noqa: ANN001, ANN202
    async def _public(host: str) -> list[str]:
        return ["93.184.216.34"]

    return ics.IcsFeedClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=resolver or _public,
    )


@pytest.mark.asyncio
async def test_fetch_returns_calendar_text() -> None:
    text = _feed(_vevent("UID:a", "DTSTART:20260903T100000Z", "SUMMARY:Hi"))
    client = _client(lambda r: httpx.Response(200, text=text))
    assert "BEGIN:VEVENT" in await client.fetch("https://example.com/cal.ics")


@pytest.mark.asyncio
async def test_fetch_follows_redirect_and_checks_each_hop() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "example.com":
            return httpx.Response(302, headers={"location": "https://cdn.example.net/cal.ics"})
        return httpx.Response(200, text=_feed())

    client = _client(handler)
    await client.fetch("https://example.com/cal.ics")
    assert seen == ["https://example.com/cal.ics", "https://cdn.example.net/cal.ics"]

    def to_private(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest"})

    with pytest.raises(ics.FeedError) as info:
        await _client(to_private).fetch("https://example.com/cal.ics")
    assert info.value.code == "private_host"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, code",
    [
        (httpx.Response(404), "feed_gone"),
        (httpx.Response(401), "feed_gone"),
        (httpx.Response(500), "http_500"),
        (httpx.Response(200, text="<html>not a calendar</html>"), "not_ics"),
        (httpx.Response(200, text="x" * (ics.MAX_FEED_BYTES + 1)), "too_large"),
    ],
)
async def test_fetch_errors(response: httpx.Response, code: str) -> None:
    with pytest.raises(ics.FeedError) as info:
        await _client(lambda r: response).fetch("https://example.com/cal.ics")
    assert info.value.code == code


@pytest.mark.asyncio
async def test_fetch_unreachable() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with pytest.raises(ics.FeedError) as info:
        await _client(boom).fetch("https://example.com/cal.ics")
    assert info.value.code == "unreachable"


# ── Parsing ──


def test_unfold_and_unescape() -> None:
    text = "BEGIN:VCALENDAR\r\nX-WR-CALNAME:Team\\, Ops\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTART:20260903T100000Z\r\nSUMMARY:Long\r\n  title\\; here\r\nDESCRIPTION:line1\\nline2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    feed = ics.parse_feed(text)
    assert feed.name == "Team, Ops"
    assert feed.events[0].summary == "Long title; here"
    assert feed.events[0].description == "line1\nline2"


def test_parse_content_line_params() -> None:
    name, params, value = ics.parse_content_line(
        'ATTENDEE;CN="Doe, Jane";PARTSTAT=ACCEPTED;CUTYPE=INDIVIDUAL:mailto:jane@x.com'
    )
    assert name == "ATTENDEE"
    assert params["CN"] == ["Doe, Jane"]
    assert params["PARTSTAT"] == ["ACCEPTED"]
    assert value == "mailto:jane@x.com"


def test_parse_when_forms() -> None:
    assert ics.parse_when("20260903", {}, default_tz=None) == date(2026, 9, 3)
    assert ics.parse_when("20260903", {"VALUE": ["DATE"]}, default_tz=None) == date(2026, 9, 3)
    assert ics.parse_when("20260903T100000Z", {}, default_tz=None) == datetime(
        2026, 9, 3, 10, tzinfo=UTC
    )
    zoned = ics.parse_when("20260903T100000", {"TZID": ["Europe/Kyiv"]}, default_tz=None)
    assert isinstance(zoned, datetime)
    assert zoned.astimezone(UTC) == datetime(2026, 9, 3, 7, tzinfo=UTC)
    floating = ics.parse_when("20260903T100000", {}, default_tz=None)
    assert floating == datetime(2026, 9, 3, 10, tzinfo=UTC)
    assert ics.parse_when("garbage", {}, default_tz=None) is None


def test_parse_duration() -> None:
    assert ics.parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert ics.parse_duration("P1D") == timedelta(days=1)
    assert ics.parse_duration("P2W") == timedelta(weeks=2)
    assert ics.parse_duration("nope") is None


# ── Expansion ──


def test_single_timed_event_in_window() -> None:
    text = _feed(
        _vevent(
            "UID:one@google.com",
            "DTSTART;TZID=Europe/Kyiv:20260903T100000",
            "DTEND;TZID=Europe/Kyiv:20260903T103000",
            "SUMMARY:Standup",
            "LOCATION:https://meet.google.com/abc-defg-hij",
            "ORGANIZER;CN=Boss:mailto:boss@x.com",
            "ATTENDEE;CN=Me;PARTSTAT=ACCEPTED:mailto:me@x.com",
            "ATTENDEE;CN=Room 1;CUTYPE=ROOM:mailto:room@x.com",
            "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:other@x.com",
            "URL:https://www.google.com/calendar/event?eid=abc",
        )
    )
    [event] = _expand(text, self_email="me@x.com")
    assert event.id == "one@google.com"
    assert event.ical_uid == "one@google.com"
    assert event.title == "Standup"
    assert event.start == datetime(2026, 9, 3, 7, tzinfo=UTC)
    assert event.end == datetime(2026, 9, 3, 7, 30, tzinfo=UTC)
    assert event.all_day is False
    assert event.meeting_url == "https://meet.google.com/abc-defg-hij"
    assert event.organizer == "boss@x.com"
    assert event.attendees == ("Me", "other@x.com")
    assert event.attendee_count == 2
    assert event.response_status == "accepted"
    assert event.html_link == "https://www.google.com/calendar/event?eid=abc"
    assert event.calendar_id == "feed"
    assert event.calendar_name == "Work"


def test_all_day_event_and_default_ends() -> None:
    text = _feed(
        _vevent(
            "UID:d", "DTSTART;VALUE=DATE:20260904", "DTEND;VALUE=DATE:20260906", "SUMMARY:Offsite"
        ),
        _vevent("UID:t", "DTSTART:20260904T090000Z", "SUMMARY:No end"),
        _vevent("UID:a", "DTSTART;VALUE=DATE:20260905"),
    )
    by_id = {e.id: e for e in _expand(text)}
    offsite = by_id["d"]
    assert offsite.all_day is True
    assert offsite.start == datetime(2026, 9, 4, tzinfo=UTC)
    assert offsite.end == datetime(2026, 9, 6, tzinfo=UTC)
    assert by_id["t"].end == datetime(2026, 9, 4, 10, tzinfo=UTC)
    assert by_id["a"].end == datetime(2026, 9, 6, tzinfo=UTC)
    assert by_id["a"].title == "(No title)"


def test_events_outside_window_and_cancelled_and_declined_are_dropped() -> None:
    text = _feed(
        _vevent("UID:past", "DTSTART:20260801T100000Z", "DTEND:20260801T110000Z", "SUMMARY:Old"),
        _vevent("UID:far", "DTSTART:20261001T100000Z", "SUMMARY:Later"),
        _vevent("UID:gone", "DTSTART:20260903T100000Z", "SUMMARY:X", "STATUS:CANCELLED"),
        _vevent(
            "UID:no",
            "DTSTART:20260903T120000Z",
            "SUMMARY:Declined",
            "ATTENDEE;PARTSTAT=DECLINED:mailto:me@x.com",
        ),
        _vevent("UID:ok", "DTSTART:20260903T130000Z", "SUMMARY:Keep"),
    )
    assert [e.id for e in _expand(text, self_email="me@x.com")] == ["ok"]


def test_weekly_rrule_expands_in_local_time_with_exdate() -> None:
    text = _feed(
        _vevent(
            "UID:weekly",
            "DTSTART;TZID=Europe/Kyiv:20260601T100000",
            "DTEND;TZID=Europe/Kyiv:20260601T101500",
            "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR",
            "EXDATE;TZID=Europe/Kyiv:20260904T100000",
            "SUMMARY:Sync",
        )
    )
    events = _expand(text)
    starts = [e.start for e in events]
    assert starts == [
        datetime(2026, 9, 2, 7, tzinfo=UTC),  # Wed
        datetime(2026, 9, 7, 7, tzinfo=UTC),  # Mon (Fri 4 Sep excluded)
        datetime(2026, 9, 9, 7, tzinfo=UTC),  # Wed
    ]
    assert events[0].id == "weekly_20260902T070000Z"
    assert all(e.ical_uid == "weekly" for e in events)


def test_daily_all_day_rrule_with_until_and_count() -> None:
    text = _feed(
        _vevent(
            "UID:daily",
            "DTSTART;VALUE=DATE:20260901",
            "RRULE:FREQ=DAILY;UNTIL=20260903",
            "SUMMARY:Sprint",
        ),
        _vevent(
            "UID:counted",
            "DTSTART:20260901T080000Z",
            "RRULE:FREQ=DAILY;COUNT=3",
            "SUMMARY:Three",
        ),
    )
    events = _expand(text)
    assert [(e.ical_uid, e.start.date()) for e in events] == [
        ("daily", date(2026, 9, 2)),
        ("counted", date(2026, 9, 2)),
        ("daily", date(2026, 9, 3)),
        ("counted", date(2026, 9, 3)),
    ]


def test_rrule_until_without_z_on_zoned_rule_is_tolerated() -> None:
    text = _feed(
        _vevent(
            "UID:u",
            "DTSTART;TZID=Europe/Kyiv:20260901T090000",
            "RRULE:FREQ=DAILY;UNTIL=20260903T090000",
            "SUMMARY:Until",
        )
    )
    assert [e.start.date() for e in _expand(text)] == [date(2026, 9, 2), date(2026, 9, 3)]


def test_recurrence_override_replaces_one_instance() -> None:
    text = _feed(
        _vevent(
            "UID:r",
            "DTSTART:20260901T100000Z",
            "DTEND:20260901T110000Z",
            "RRULE:FREQ=DAILY;COUNT=5",
            "SUMMARY:Daily",
        ),
        _vevent(
            "UID:r",
            "RECURRENCE-ID:20260903T100000Z",
            "DTSTART:20260903T150000Z",
            "DTEND:20260903T160000Z",
            "SUMMARY:Daily (moved)",
        ),
        _vevent(
            "UID:r",
            "RECURRENCE-ID:20260904T100000Z",
            "DTSTART:20260904T100000Z",
            "SUMMARY:Daily",
            "STATUS:CANCELLED",
        ),
    )
    events = _expand(text)
    assert [(e.start, e.title) for e in events] == [
        (datetime(2026, 9, 2, 10, tzinfo=UTC), "Daily"),
        (datetime(2026, 9, 3, 15, tzinfo=UTC), "Daily (moved)"),
        (datetime(2026, 9, 5, 10, tzinfo=UTC), "Daily"),
    ]


def test_rdate_adds_an_instance() -> None:
    text = _feed(
        _vevent(
            "UID:rd",
            "DTSTART:20260801T100000Z",
            "RDATE:20260905T100000Z",
            "SUMMARY:Extra",
        )
    )
    assert [e.start for e in _expand(text)] == [datetime(2026, 9, 5, 10, tzinfo=UTC)]


def test_unknown_tzid_falls_back_to_feed_timezone() -> None:
    text = _feed(
        _vevent("UID:w", "DTSTART;TZID=W. Europe Standard Time:20260903T100000", "SUMMARY:Win"),
        tz="Europe/Berlin",
    )
    [event] = _expand(text)
    assert event.start == datetime(2026, 9, 3, 8, tzinfo=UTC)


def test_google_conference_property_wins_over_text() -> None:
    text = _feed(
        _vevent(
            "UID:g",
            "DTSTART:20260903T100000Z",
            "SUMMARY:Call",
            "X-GOOGLE-CONFERENCE:https://meet.google.com/xyz-abcd-efg",
            "DESCRIPTION:Join https://zoom.us/j/123",
        )
    )
    [event] = _expand(text)
    assert event.meeting_url == "https://meet.google.com/xyz-abcd-efg"


def test_bad_rrule_is_skipped_not_fatal() -> None:
    text = _feed(
        _vevent("UID:bad", "DTSTART:20260903T100000Z", "RRULE:FREQ=NOPE", "SUMMARY:Bad"),
        _vevent("UID:ok", "DTSTART:20260903T110000Z", "SUMMARY:Ok"),
    )
    assert [e.id for e in _expand(text)] == ["ok"]


def test_occurrence_cap() -> None:
    text = _feed(
        _vevent("UID:m", "DTSTART:20260902T000000Z", "RRULE:FREQ=MINUTELY", "SUMMARY:Spam")
    )
    assert len(_expand(text)) == ics.MAX_OCCURRENCES_PER_EVENT


# ── Labels ──


def test_feed_label_and_self_email() -> None:
    feed = ics.parse_feed(_feed(name="me@x.com"))
    assert ics.feed_label(feed, "https://calendar.google.com/x") == "me@x.com"
    assert ics.self_email_from_label("me@x.com") == "me@x.com"
    unnamed = ics.parse_feed(_feed(name=""))
    assert ics.feed_label(unnamed, "https://calendar.google.com/x") == "calendar.google.com"
    assert ics.self_email_from_label("Team calendar") is None
