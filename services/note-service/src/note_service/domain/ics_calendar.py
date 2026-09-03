"""Calendar links — iCal/ICS feeds the service fetches and parses (0020).

The no-OAuth way in: every calendar product publishes a private
subscription address (Google Calendar → *Settings → Integrate calendar →
Secret address in iCal format*; Outlook → *Publish calendar*; iCloud →
*Public calendar*). The user pastes it, the service fetches it on every
"Coming up" read and expands it into ``CalendarEvent`` rows shaped
exactly like the Google ones, so the merge, the picker and the clients do
not know the difference.

Only the subset of RFC 5545 a "next seven days" list needs is handled:
VEVENT with DTSTART/DTEND/DURATION, all-day (``VALUE=DATE``) and timed
events, ``TZID`` via zoneinfo, RRULE/RDATE/EXDATE expansion through
``dateutil.rrule``, RECURRENCE-ID overrides, cancelled and declined
instances. Anything else is ignored rather than rejected.

Fetching a user-supplied URL is the risky part: the host must be public
(no loopback, RFC 1918, link-local, or metadata addresses — resolved
before the request and again after every redirect), the scheme https,
the body capped.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from dateutil import rrule as du_rrule

from .google_calendar import CalendarEvent, CalendarInfo, find_meeting_url

logger = logging.getLogger(__name__)

# The one "calendar" a link exposes, for the picker and hidden_calendar_ids.
FEED_CALENDAR_ID = "feed"

MAX_URL_LENGTH = 2048
MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
# A weekly standup expanded over a 7-day window is a handful; the cap is
# against a feed that repeats every minute.
MAX_OCCURRENCES_PER_EVENT = 200
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
_USER_AGENT = "NotesAI-Calendar/1.0 (+ics)"

Resolver = Callable[[str], Awaitable[list[str]]]


class FeedError(Exception):
    """The link could not be fetched or is not a calendar."""

    def __init__(self, message: str, *, code: str = "feed_error", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


# ── URL policy ──────────────────────────────────────────────────────

_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain", ".home.arpa")


def normalize_feed_url(raw: str) -> str:
    """Canonical https URL of a feed, or ``FeedError`` (code ``bad_url``).

    ``webcal://`` (what Apple and many "subscribe" buttons hand out) is the
    same thing over https. Credentials in the URL, fragments and
    non-https schemes are refused."""
    candidate = (raw or "").strip()
    if not candidate or len(candidate) > MAX_URL_LENGTH or any(c in candidate for c in "\r\n\t "):
        raise FeedError("Paste the https:// address of a calendar feed.", code="bad_url")
    lowered = candidate.lower()
    for prefix in ("webcal://", "webcals://"):
        if lowered.startswith(prefix):
            candidate = "https://" + candidate[len(prefix) :]
            break
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        raise FeedError("Calendar links must start with https:// (or webcal://).", code="bad_url")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host or parts.username or parts.password:
        raise FeedError("Paste the https:// address of a calendar feed.", code="bad_url")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise FeedError("That address points at a private network.", code="private_host")
    literal = _ip_literal(host)
    if literal is not None and not _is_public_ip(literal):
        raise FeedError("That address points at a private network.", code="private_host")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def feed_fingerprint(url: str) -> str:
    """sha256 of the canonical URL: the row's duplicate key, never the URL itself."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise FeedError(f"Could not resolve {host}.", code="unresolvable") from exc
    return [str(info[4][0]) for info in infos]


async def assert_public_host(url: str, resolver: Resolver) -> None:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    literal = _ip_literal(host)
    addresses = [str(literal)] if literal else await resolver(host)
    if not addresses:
        raise FeedError(f"Could not resolve {host}.", code="unresolvable")
    for address in addresses:
        parsed = _ip_literal(address)
        if parsed is None or not _is_public_ip(parsed):
            raise FeedError("That address points at a private network.", code="private_host")


# ── Fetching ────────────────────────────────────────────────────────


class IcsFeedClient:
    """GET the feed with the URL policy applied at every hop."""

    def __init__(
        self, *, http: httpx.AsyncClient | None = None, resolver: Resolver | None = None
    ) -> None:
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        self._resolver = resolver or _default_resolver

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self, url: str) -> str:
        current = normalize_feed_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            await assert_public_host(current, self._resolver)
            try:
                async with self._http.stream(
                    "GET",
                    current,
                    headers={"User-Agent": _USER_AGENT, "Accept": "text/calendar, */*;q=0.5"},
                    follow_redirects=False,
                ) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get(
                        "location"
                    ):
                        current = normalize_feed_url(urljoin(current, resp.headers["location"]))
                        continue
                    if resp.status_code in (401, 403, 404, 410):
                        raise FeedError(
                            "The link no longer works. Get a fresh address from the calendar "
                            "and add it again.",
                            code="feed_gone",
                            status=resp.status_code,
                        )
                    if resp.status_code != 200:
                        raise FeedError(
                            f"The calendar answered HTTP {resp.status_code}.",
                            code=f"http_{resp.status_code}",
                            status=resp.status_code,
                        )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_FEED_BYTES:
                            raise FeedError("The calendar feed is too large.", code="too_large")
                        chunks.append(chunk)
            except httpx.HTTPError as exc:
                raise FeedError(
                    f"Could not reach the calendar: {exc.__class__.__name__}", code="unreachable"
                ) from exc
            text = b"".join(chunks).decode("utf-8", errors="replace")
            if "BEGIN:VCALENDAR" not in text[:4096].upper():
                raise FeedError(
                    "That address did not return a calendar (no VCALENDAR).", code="not_ics"
                )
            return text
        raise FeedError("Too many redirects.", code="too_many_redirects")


# ── Parsing ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class Attendee:
    address: str | None
    name: str | None
    partstat: str | None
    resource: bool = False


@dataclass(slots=True)
class RawEvent:
    uid: str
    summary: str
    dtstart: datetime | date
    dtend: datetime | date | None = None
    duration: timedelta | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None
    status: str | None = None
    organizer: str | None = None
    attendees: list[Attendee] = field(default_factory=list)
    rrule: str | None = None
    rdates: list[datetime | date] = field(default_factory=list)
    exdates: list[datetime | date] = field(default_factory=list)
    recurrence_id: datetime | date | None = None
    conference_url: str | None = None


@dataclass(slots=True)
class ParsedFeed:
    name: str | None
    timezone: str | None
    events: list[RawEvent]


def unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with a space or tab
    continues the previous one."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line:
            continue
        if line[0] in " \t" and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_content_line(line: str) -> tuple[str, dict[str, list[str]], str]:
    """``NAME;PARAM=a,b;OTHER="x:y":value`` → (NAME, {PARAM: [a, b], …}, value)."""
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:index], line[index + 1 :]
            break
    else:
        head, value = line, ""
    pieces = _split_unquoted(head, ";")
    name = pieces[0].strip().upper()
    params: dict[str, list[str]] = {}
    for piece in pieces[1:]:
        key, _, raw = piece.partition("=")
        values = [v.strip().strip('"') for v in _split_unquoted(raw, ",")]
        params[key.strip().upper()] = values
    return name, params, value


def _split_unquoted(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        if char == sep and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


_UNESCAPE = re.compile(r"\\([\\;,nN])")


def unescape_text(value: str) -> str:
    return _UNESCAPE.sub(lambda m: "\n" if m.group(1) in "nN" else m.group(1), value).strip()


def _zone(tzid: str | None, default: ZoneInfo | None) -> ZoneInfo | None:
    if not tzid:
        return default
    try:
        return ZoneInfo(tzid.strip('"'))
    except (KeyError, ValueError, OSError):
        # Windows names ("W. Europe Standard Time") and custom ids land
        # here; the feed's own X-WR-TIMEZONE is the next best guess.
        logger.info("calendar.ics.unknown_tzid", extra={"tzid": tzid[:64]})
        return default


def parse_when(
    value: str, params: dict[str, list[str]], *, default_tz: ZoneInfo | None
) -> datetime | date | None:
    """DATE (``20260902``), UTC (``20260902T100000Z``), zoned (``TZID=…``)
    or floating (``20260902T100000``, taken in the feed's zone or UTC)."""
    text = value.strip()
    if params.get("VALUE", [""])[0].upper() == "DATE" or (len(text) == 8 and text.isdigit()):
        try:
            return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    utc = text.endswith("Z")
    core = text[:-1] if utc else text
    try:
        naive = datetime.strptime(core, "%Y%m%dT%H%M%S")
    except ValueError:
        try:
            naive = datetime.strptime(core, "%Y%m%dT%H%M")
        except ValueError:
            return None
    if utc:
        return naive.replace(tzinfo=UTC)
    zone = _zone(params.get("TZID", [None])[0], default_tz)
    return naive.replace(tzinfo=zone or UTC)


_DURATION_RE = re.compile(
    r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def parse_duration(value: str) -> timedelta | None:
    match = _DURATION_RE.match(value.strip())
    if not match:
        return None
    sign, weeks, days, hours, minutes, seconds = match.groups()
    delta = timedelta(
        weeks=int(weeks or 0),
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(seconds or 0),
    )
    return -delta if sign == "-" else delta


def _mailto(value: str) -> str | None:
    text = value.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    return text.strip().lower() or None


def parse_feed(text: str) -> ParsedFeed:
    name: str | None = None
    timezone: str | None = None
    default_tz: ZoneInfo | None = None
    events: list[RawEvent] = []
    stack: list[str] = []
    props: list[tuple[str, dict[str, list[str]], str]] = []

    for line in unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            stack.append(upper[6:].strip())
            if stack[-1] == "VEVENT":
                props = []
            continue
        if upper.startswith("END:"):
            component = upper[4:].strip()
            if stack and stack[-1] == component:
                stack.pop()
            if component == "VEVENT":
                event = _build_event(props, default_tz=default_tz)
                if event is not None:
                    events.append(event)
                props = []
            continue
        if not stack:
            continue
        current = stack[-1]
        if current == "VCALENDAR":
            prop, params, value = parse_content_line(line)
            if prop == "X-WR-CALNAME":
                name = unescape_text(value) or None
            elif prop == "X-WR-TIMEZONE":
                timezone = value.strip() or None
                default_tz = _zone(timezone, None)
        elif current == "VEVENT":
            props.append(parse_content_line(line))
        # VALARM, VTIMEZONE, VTODO…: skipped.
    return ParsedFeed(name=name, timezone=timezone, events=events)


def _build_event(
    props: list[tuple[str, dict[str, list[str]], str]], *, default_tz: ZoneInfo | None
) -> RawEvent | None:
    uid = ""
    summary = ""
    dtstart: datetime | date | None = None
    event = RawEvent(uid="", summary="", dtstart=date.today())
    for prop, params, value in props:
        if prop == "UID":
            uid = value.strip()
        elif prop == "SUMMARY":
            summary = unescape_text(value)
        elif prop == "DTSTART":
            dtstart = parse_when(value, params, default_tz=default_tz)
        elif prop == "DTEND":
            event.dtend = parse_when(value, params, default_tz=default_tz)
        elif prop == "DURATION":
            event.duration = parse_duration(value)
        elif prop == "LOCATION":
            event.location = unescape_text(value) or None
        elif prop == "DESCRIPTION":
            event.description = unescape_text(value) or None
        elif prop == "URL":
            event.url = value.strip() or None
        elif prop == "STATUS":
            event.status = value.strip().upper() or None
        elif prop == "ORGANIZER":
            event.organizer = _mailto(value) or (params.get("CN", [None])[0])
        elif prop == "ATTENDEE":
            cutype = (params.get("CUTYPE", [""])[0] or "").upper()
            event.attendees.append(
                Attendee(
                    address=_mailto(value),
                    name=params.get("CN", [None])[0],
                    partstat=(params.get("PARTSTAT", [None])[0] or None),
                    resource=cutype in ("RESOURCE", "ROOM"),
                )
            )
        elif prop == "RRULE":
            event.rrule = value.strip() or None
        elif prop == "RDATE":
            for piece in value.split(","):
                when = parse_when(piece, params, default_tz=default_tz)
                if when is not None:
                    event.rdates.append(when)
        elif prop == "EXDATE":
            for piece in value.split(","):
                when = parse_when(piece, params, default_tz=default_tz)
                if when is not None:
                    event.exdates.append(when)
        elif prop == "RECURRENCE-ID":
            event.recurrence_id = parse_when(value, params, default_tz=default_tz)
        elif prop == "X-GOOGLE-CONFERENCE":
            event.conference_url = value.strip() or None
    if dtstart is None:
        return None
    event.uid = uid or f"{summary}|{dtstart.isoformat()}"
    event.summary = summary
    event.dtstart = dtstart
    return event


# ── Expansion ───────────────────────────────────────────────────────


def _as_utc(when: datetime | date) -> datetime:
    if isinstance(when, datetime):
        return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    return datetime(when.year, when.month, when.day, tzinfo=UTC)


def _instance_key(when: datetime | date) -> str:
    """What EXDATE / RECURRENCE-ID match against: the instant for timed
    events, the day for all-day ones."""
    if isinstance(when, datetime):
        return _as_utc(when).strftime("%Y%m%dT%H%M%SZ")
    return when.strftime("%Y%m%d")


def event_duration(event: RawEvent) -> timedelta:
    if event.dtend is not None:
        delta = _as_utc(event.dtend) - _as_utc(event.dtstart)
        if delta > timedelta(0):
            return delta
    if event.duration is not None and event.duration > timedelta(0):
        return event.duration
    # Same defaults as the Google normaliser: a day, or an hour.
    return timedelta(days=1) if not isinstance(event.dtstart, datetime) else timedelta(hours=1)


def _normalize_rrule(rule: str, *, aware: bool) -> str:
    """dateutil insists that UNTIL and DTSTART agree on time-zone-ness;
    feeds do not always oblige (a DATE until on a timed rule, or a
    zoned until without ``Z``)."""
    parts: list[str] = []
    for part in rule.split(";"):
        key, _, value = part.partition("=")
        if key.upper() == "UNTIL":
            value = value.strip()
            if aware:
                if len(value) == 8:
                    value += "T235959Z"
                elif not value.endswith("Z"):
                    value += "Z"
            else:
                value = value[:8]
        parts.append(f"{key}={value}")
    return ";".join(parts)


def occurrences(
    event: RawEvent, *, time_min: datetime, time_max: datetime
) -> list[datetime | date]:
    """Start instants (or days) of the event inside the window, expanded
    from RRULE/RDATE and minus EXDATE. A non-recurring event yields its
    own start when it overlaps the window."""
    all_day = not isinstance(event.dtstart, datetime)
    duration = event_duration(event)
    if not event.rrule and not event.rdates:
        start = _as_utc(event.dtstart)
        return [event.dtstart] if start < time_max and start + duration > time_min else []

    if all_day:
        assert isinstance(event.dtstart, date)
        dtstart: datetime = datetime(
            event.dtstart.year, event.dtstart.month, event.dtstart.day
        )  # naive
        lower = (time_min - duration).astimezone(UTC).replace(tzinfo=None)
        upper = time_max.astimezone(UTC).replace(tzinfo=None)
    else:
        assert isinstance(event.dtstart, datetime)
        dtstart = event.dtstart if event.dtstart.tzinfo else event.dtstart.replace(tzinfo=UTC)
        lower = (time_min - duration).astimezone(UTC)
        upper = time_max.astimezone(UTC)

    rules = du_rrule.rruleset()
    if event.rrule:
        try:
            rules.rrule(
                du_rrule.rrulestr(_normalize_rrule(event.rrule, aware=not all_day), dtstart=dtstart)
            )
        except (ValueError, TypeError, KeyError) as exc:
            logger.info(
                "calendar.ics.bad_rrule",
                extra={"rrule": event.rrule[:120], "error": str(exc)[:120]},
            )
            return []
    else:
        rules.rdate(dtstart)
    for extra in event.rdates:
        if isinstance(extra, datetime):
            if not all_day:
                rules.rdate(extra if extra.tzinfo else extra.replace(tzinfo=UTC))
        elif all_day:
            rules.rdate(datetime(extra.year, extra.month, extra.day))
    excluded = {_instance_key(x) for x in event.exdates}

    out: list[datetime | date] = []
    for when in rules.between(lower, upper, inc=True):
        candidate: datetime | date = when.date() if all_day else when
        if _instance_key(candidate) in excluded:
            continue
        instant = _as_utc(candidate)
        if instant + duration <= time_min or instant >= time_max:
            continue
        out.append(candidate)
        if len(out) >= MAX_OCCURRENCES_PER_EVENT:
            break
    return out


_PARTSTAT = {
    "ACCEPTED": "accepted",
    "TENTATIVE": "tentative",
    "NEEDS-ACTION": "needsAction",
    "DECLINED": "declined",
}


def to_calendar_event(
    event: RawEvent,
    start: datetime | date,
    *,
    calendar: CalendarInfo,
    self_email: str | None,
    instance: bool,
) -> CalendarEvent | None:
    all_day = not isinstance(start, datetime)
    start_at = _as_utc(start)
    end_at = start_at + event_duration(event)

    response_status: str | None = None
    if self_email:
        for attendee in event.attendees:
            if attendee.address == self_email:
                response_status = _PARTSTAT.get((attendee.partstat or "").upper())
                break
    if response_status == "declined":
        return None

    names = tuple(
        (attendee.name or attendee.address or "").strip()
        for attendee in event.attendees
        if not attendee.resource and (attendee.name or attendee.address)
    )
    meeting_url = event.conference_url or find_meeting_url(
        {"location": event.location, "description": event.description, "url": event.url}
    )
    html_link = event.url if event.url and event.url.startswith(("https://", "http://")) else None
    return CalendarEvent(
        id=f"{event.uid}_{start_at.strftime('%Y%m%dT%H%M%SZ')}" if instance else event.uid,
        ical_uid=event.uid,
        calendar_id=calendar.id,
        calendar_name=calendar.name,
        color=calendar.color,
        title=event.summary.strip() or "(No title)",
        start=start_at,
        end=end_at,
        all_day=all_day,
        location=event.location,
        meeting_url=meeting_url,
        html_link=html_link,
        attendee_count=len(names),
        organizer=event.organizer,
        response_status=response_status,
        attendees=names[:12],
    )


def upcoming_events(
    feed: ParsedFeed,
    *,
    calendar: CalendarInfo,
    time_min: datetime,
    time_max: datetime,
    self_email: str | None = None,
) -> list[CalendarEvent]:
    """Every occurrence in [time_min, time_max) as ``CalendarEvent``s:
    masters expanded, overridden instances (RECURRENCE-ID) swapped in,
    cancelled ones dropped."""
    masters: dict[str, RawEvent] = {}
    overrides: dict[str, list[RawEvent]] = {}
    for event in feed.events:
        if event.recurrence_id is None:
            masters.setdefault(event.uid, event)
        else:
            overrides.setdefault(event.uid, []).append(event)

    out: list[CalendarEvent] = []
    for uid, master in masters.items():
        replaced = {
            _instance_key(o.recurrence_id) for o in overrides.get(uid, []) if o.recurrence_id
        }
        if master.status == "CANCELLED":
            continue
        recurring = bool(master.rrule or master.rdates)
        for start in occurrences(master, time_min=time_min, time_max=time_max):
            if _instance_key(start) in replaced:
                continue
            built = to_calendar_event(
                master, start, calendar=calendar, self_email=self_email, instance=recurring
            )
            if built is not None:
                out.append(built)
    for items in overrides.values():
        for override in items:
            if override.status == "CANCELLED":
                continue
            for start in occurrences(override, time_min=time_min, time_max=time_max):
                built = to_calendar_event(
                    override, start, calendar=calendar, self_email=self_email, instance=True
                )
                if built is not None:
                    out.append(built)
    out.sort(key=lambda e: (e.start, e.title.lower()))
    return out


def feed_label(feed: ParsedFeed, url: str) -> str:
    """What the clients show for the link: the calendar's own name, else its host."""
    name = (feed.name or "").strip()
    if name:
        return name[:120]
    return (urlsplit(url).hostname or "calendar")[:120]


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def self_email_from_label(label: str) -> str | None:
    """Google names the primary calendar's feed after the account, which
    is the only hint a feed gives about who "you" are."""
    text = label.strip().lower()
    return text if _EMAIL_RE.match(text) else None
