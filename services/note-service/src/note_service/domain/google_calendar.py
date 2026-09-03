"""Google Calendar — OAuth and the read-only events API (0019).

A thin, testable client over Google's REST endpoints (no google-* SDK:
four requests do not justify a dependency tree). The HTTP transport is
injected, so tests drive it with ``httpx.MockTransport``.

Scopes: ``calendar.readonly`` (events and the calendar list) plus
``openid email`` so the account can be named in the UI. Nothing here can
write to the user's calendar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.readonly",
)

# Per-calendar cap; the merged list is capped again in calendar_sync.
_MAX_EVENTS_PER_CALENDAR = 50
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


class GoogleError(Exception):
    """Google answered with an error (HTTP status or OAuth error code)."""

    def __init__(self, message: str, *, code: str = "google_error", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class NeedsReauthError(GoogleError):
    """The refresh token is dead: the user must connect the account again."""

    def __init__(self, message: str = "Google refused the refresh token") -> None:
        super().__init__(message, code="needs_reauth", status=401)


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarInfo:
    id: str
    name: str
    color: str | None
    primary: bool
    # Google's own "shown in the UI" flag; we surface it as a hint only.
    selected: bool


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str
    # iCalUID is stable across the copies an invite makes in several
    # calendars; used to drop duplicates when merging.
    ical_uid: str
    calendar_id: str
    calendar_name: str
    color: str | None
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    meeting_url: str | None
    html_link: str | None
    attendee_count: int
    organizer: str | None
    # The user's own RSVP: accepted | tentative | needsAction | declined | None (own event).
    response_status: str | None
    attendees: tuple[str, ...] = field(default=())


# ── Wire parsing ────────────────────────────────────────────────────


def _parse_when(part: dict[str, Any] | None) -> tuple[datetime, bool] | None:
    """Google gives ``{"dateTime": iso}`` for timed events and ``{"date": "YYYY-MM-DD"}``
    for all-day ones. All-day bounds come back as midnight UTC of that day."""
    if not part:
        return None
    if part.get("dateTime"):
        raw = str(part["dateTime"]).replace("Z", "+00:00")
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC), False
    if part.get("date"):
        try:
            day = date.fromisoformat(str(part["date"]))
        except ValueError:
            return None
        return datetime(day.year, day.month, day.day, tzinfo=UTC), True
    return None


def find_meeting_url(raw: dict[str, Any]) -> str | None:
    """A video-call link: Google's own fields first, then anything that
    looks like Zoom/Teams/Meet in the location or description. Shared with
    the ICS path (domain/ics_calendar), which only has the text fields."""
    if raw.get("hangoutLink"):
        return str(raw["hangoutLink"])
    conference = raw.get("conferenceData") or {}
    for entry in conference.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return str(entry["uri"])
    for entry in conference.get("entryPoints") or []:
        if entry.get("uri", "").startswith("http"):
            return str(entry["uri"])
    # Zoom / Teams links usually sit in the location or description.
    for key in ("location", "description"):
        text = str(raw.get(key) or "")
        for token in text.split():
            if token.startswith(("https://", "http://")) and any(
                host in token
                for host in (
                    "zoom.us",
                    "teams.microsoft.com",
                    "meet.google.com",
                    "whereby.com",
                    "webex.com",
                )
            ):
                return token.rstrip(").,>")
    return None


def normalize_event(raw: dict[str, Any], calendar: CalendarInfo) -> CalendarEvent | None:
    """One Google event → ``CalendarEvent``; ``None`` for the ones to skip
    (cancelled, declined by the user, or without usable times)."""
    if raw.get("status") == "cancelled":
        return None
    start = _parse_when(raw.get("start"))
    end = _parse_when(raw.get("end"))
    if start is None:
        return None
    start_at, all_day = start
    end_at = (
        end[0]
        if end
        else (start_at + timedelta(days=1) if all_day else start_at + timedelta(hours=1))
    )

    attendees_raw = raw.get("attendees") or []
    response_status: str | None = None
    for attendee in attendees_raw:
        if attendee.get("self"):
            response_status = attendee.get("responseStatus")
            break
    if response_status == "declined":
        return None

    organizer = (raw.get("organizer") or {}).get("email")
    names = tuple(
        str(a.get("displayName") or a.get("email") or "")
        for a in attendees_raw
        if not a.get("resource") and (a.get("displayName") or a.get("email"))
    )
    return CalendarEvent(
        id=str(raw.get("id") or ""),
        ical_uid=str(raw.get("iCalUID") or raw.get("id") or ""),
        calendar_id=calendar.id,
        calendar_name=calendar.name,
        color=calendar.color,
        title=str(raw.get("summary") or "").strip() or "(No title)",
        start=start_at,
        end=end_at,
        all_day=all_day,
        location=(str(raw["location"]).strip() or None) if raw.get("location") else None,
        meeting_url=find_meeting_url(raw),
        html_link=str(raw["htmlLink"]) if raw.get("htmlLink") else None,
        attendee_count=len(names),
        organizer=str(organizer) if organizer else None,
        response_status=response_status,
        attendees=names[:12],
    )


# ── Client ──────────────────────────────────────────────────────────


class GoogleCalendarClient:
    """OAuth + Calendar API calls. ``configured`` is False when the
    deployment has no Google client id — every route then answers 503
    for connect and ``available: false`` for reads."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self._client_secret)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── OAuth ──

    def authorize_url(self, *, state: str, login_hint: str | None = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            # offline + consent: Google only issues a refresh token on a
            # consent screen; without it a reconnect returns none.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> TokenSet:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        tokens = await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        # Google does not echo the refresh token on refresh; keep ours.
        if tokens.refresh_token is None:
            tokens = TokenSet(
                access_token=tokens.access_token,
                refresh_token=refresh_token,
                expires_at=tokens.expires_at,
                scopes=tokens.scopes,
            )
        return tokens

    async def _token_request(self, form: dict[str, str]) -> TokenSet:
        data = dict(form)
        data["client_id"] = self.client_id
        data["client_secret"] = self._client_secret
        try:
            resp = await self._http.post(TOKEN_ENDPOINT, data=data)
        except httpx.HTTPError as exc:
            raise GoogleError(
                f"could not reach Google: {exc.__class__.__name__}", code="unreachable"
            ) from exc
        body = _json(resp)
        if resp.status_code != 200 or "access_token" not in body:
            error = str(body.get("error") or f"http_{resp.status_code}")
            if error == "invalid_grant":
                raise NeedsReauthError()
            raise GoogleError(
                str(body.get("error_description") or error), code=error, status=resp.status_code
            )
        expires_in = body.get("expires_in")
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in))
            if expires_in is not None
            else None
        )
        scopes = tuple(str(body.get("scope") or "").split())
        return TokenSet(
            access_token=str(body["access_token"]),
            refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
            expires_at=expires_at,
            scopes=scopes,
        )

    async def revoke(self, token: str) -> None:
        """Best effort: Google answers 400 for an already-dead token, which
        is the outcome we wanted anyway."""
        try:
            await self._http.post(REVOKE_ENDPOINT, data={"token": token})
        except httpx.HTTPError as exc:
            logger.info("calendar.google.revoke_failed", extra={"error": exc.__class__.__name__})

    async def account_email(self, access_token: str) -> str:
        body = await self._get(USERINFO_ENDPOINT, access_token)
        email = str(body.get("email") or "").strip().lower()
        if not email:
            raise GoogleError("Google did not return the account's e-mail", code="no_email")
        return email

    # ── Calendar API ──

    async def list_calendars(self, access_token: str) -> list[CalendarInfo]:
        out: list[CalendarInfo] = []
        page: str | None = None
        while True:
            params: dict[str, str] = {"minAccessRole": "reader", "maxResults": "250"}
            if page:
                params["pageToken"] = page
            body = await self._get(
                f"{CALENDAR_API}/users/me/calendarList", access_token, params=params
            )
            for item in body.get("items") or []:
                if item.get("deleted"):
                    continue
                out.append(
                    CalendarInfo(
                        id=str(item["id"]),
                        name=str(item.get("summaryOverride") or item.get("summary") or item["id"]),
                        color=str(item["backgroundColor"]) if item.get("backgroundColor") else None,
                        primary=bool(item.get("primary")),
                        selected=bool(item.get("selected", True)),
                    )
                )
            page = body.get("nextPageToken")
            if not page:
                break
        # Primary first, then alphabetical: the order the picker shows.
        out.sort(key=lambda c: (not c.primary, c.name.lower()))
        return out

    async def list_events(
        self,
        access_token: str,
        calendar: CalendarInfo,
        *,
        time_min: datetime,
        time_max: datetime,
    ) -> list[CalendarEvent]:
        params = {
            "timeMin": time_min.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": time_max.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(_MAX_EVENTS_PER_CALENDAR),
            "showDeleted": "false",
        }
        body = await self._get(
            f"{CALENDAR_API}/calendars/{quote(calendar.id, safe='')}/events",
            access_token,
            params=params,
        )
        events: list[CalendarEvent] = []
        for raw in body.get("items") or []:
            event = normalize_event(raw, calendar)
            if event is not None:
                events.append(event)
        return events

    async def _get(
        self, url: str, access_token: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            resp = await self._http.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as exc:
            raise GoogleError(
                f"could not reach Google: {exc.__class__.__name__}", code="unreachable"
            ) from exc
        if resp.status_code == 401:
            raise GoogleError("Google rejected the access token", code="unauthorized", status=401)
        if resp.status_code != 200:
            body = _json(resp)
            message = str(
                (body.get("error") or {}).get("message")
                if isinstance(body.get("error"), dict)
                else body.get("error") or f"HTTP {resp.status_code}"
            )
            raise GoogleError(message, code=f"http_{resp.status_code}", status=resp.status_code)
        return _json(resp)


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
