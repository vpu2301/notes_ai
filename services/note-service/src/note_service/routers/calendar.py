"""Calendar connections and the "Coming up" list (0019, 0020).

    GET    /v1/calendar/connections                    the user's connected accounts and links
    POST   /v1/calendar/google/connect                 start Google sign-in → {authorize_url}
    GET    /v1/calendar/google/callback                Google sends the browser back here
    POST   /v1/calendar/ics/connect                    add a calendar link (iCal address) → connection
    DELETE /v1/calendar/connections/{id}               disconnect (revoke at Google, keep the row)
    GET    /v1/calendar/connections/{id}/calendars     the account's calendars, with shown flags
    PUT    /v1/calendar/connections/{id}/calendars     which of them feed the list
    GET    /v1/calendar/events?days=7                  upcoming events across every account

Connections are personal: every route filters on the caller's ``sub``
on top of tenant RLS. The callback is the one unauthenticated route —
a browser navigation from Google carries no bearer token — and it trusts
only what the HMAC-signed ``state`` says (domain/calendar_state).

Both clients drive the same flow. They differ in ``return_to``: the web
app asks to come back to its own origin, the Mac app to its
``notesai://`` scheme, which ASWebAuthenticationSession intercepts.

A calendar link (0020) needs no Google client at all: the user pastes
the calendar's private iCal address, the service fetches it once to
check it is a calendar, seals the URL and stores it as a connection with
``provider = "ics"``. From there it behaves like an account with one
calendar.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from crypto import CryptoError
from db import tenant_connection

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import calendar_repository as repo
from ..domain import calendar_sync
from ..domain.calendar_state import InvalidStateError, issue_state, verify_state
from ..domain.google_calendar import GoogleError, NeedsReauthError
from ..domain.ics_calendar import (
    FEED_CALENDAR_ID,
    FeedError,
    feed_fingerprint,
    feed_label,
    normalize_feed_url,
    parse_feed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/calendar", tags=["calendar"])

_MAX_DAYS = 31


# ── Wire models ─────────────────────────────────────────────────────


class ConnectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    provider: str
    account_email: str
    connected_at: str
    hidden_calendar_ids: list[str]
    needs_reauth: bool
    last_synced_at: str | None
    last_error: str | None


class ConnectionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # False when the deployment has no Google client configured: the
    # clients hide the connect button instead of showing a dead one.
    available: bool
    # 0020: calendar links need nothing from the deployment; True lets an
    # older client tell this server from one without the route.
    link_available: bool = True
    connections: list[ConnectionView]


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Where the browser lands after Google: the web app's origin (plus a
    # path) or the Mac app's notesai:// URL. Must match an allowed prefix.
    return_to: str = Field(min_length=1, max_length=1024)
    login_hint: str | None = Field(default=None, max_length=254)


class ConnectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorize_url: str


class LinkConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The calendar's private iCal address (https:// or webcal://).
    url: str = Field(min_length=1, max_length=2048)
    # Optional display name; defaults to the calendar's own name.
    label: str | None = Field(default=None, max_length=120)


class CalendarView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    color: str | None
    primary: bool
    shown: bool


class CalendarsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    calendars: list[CalendarView]


class CalendarsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hidden_calendar_ids: list[str] = Field(max_length=500)


class EventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    connection_id: UUID
    account_email: str
    calendar_id: str
    calendar_name: str
    color: str | None
    title: str
    start: str
    end: str
    all_day: bool
    location: str | None
    meeting_url: str | None
    html_link: str | None
    attendee_count: int
    attendees: list[str]
    organizer: str | None
    response_status: str | None


class ProblemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    account_email: str
    code: str
    message: str
    needs_reauth: bool


class EventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    connected: bool
    events: list[EventView]
    problems: list[ProblemView]
    fetched_at: str


# ── Helpers ─────────────────────────────────────────────────────────


def _iso(when: datetime | None) -> str | None:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z") if when else None


def _connection_view(row: repo.ConnectionRow) -> ConnectionView:
    return ConnectionView(
        id=row.id,
        provider=row.provider,
        account_email=row.account_email,
        connected_at=_iso(row.created_at) or "",
        hidden_calendar_ids=list(row.hidden_calendar_ids),
        needs_reauth=row.needs_reauth,
        last_synced_at=_iso(row.last_synced_at),
        last_error=row.last_error,
    )


def return_to_allowed(return_to: str, prefixes: list[str]) -> bool:
    """A return_to is accepted when it starts with an allowed prefix AND
    the character after the prefix cannot extend the host (so
    ``http://localhost:5173.evil.com`` does not pass for ``http://localhost:5173``)."""
    candidate = return_to.strip()
    if not candidate or any(c in candidate for c in "\r\n\t "):
        return False
    for prefix in prefixes:
        if not candidate.startswith(prefix):
            continue
        rest = candidate[len(prefix) :]
        if prefix.endswith("://") or rest == "" or rest[0] in "/?#":
            return True
    return False


def _with_query(url: str, **params: str) -> str:
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{urlencode(params)}"


async def _audit(
    claims: Claims, kind: str, connection_id: UUID, payload: dict[str, object]
) -> None:
    state = get_state()
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="calendar_connection",
        target_id=connection_id,
        payload=payload,
        severity=Severity.INFO,
    )


def _not_configured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Google Calendar is not configured on this server (GOOGLE_CALENDAR_CLIENT_ID).",
    )


_reader = requires("note.read", "note")


# ── Connections ─────────────────────────────────────────────────────


@router.get("/connections", response_model=ConnectionsResponse)
async def list_connections(
    claims: Annotated[Claims, Depends(_reader)],
) -> ConnectionsResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = await repo.list_live(conn, user_sub=claims.sub)
    return ConnectionsResponse(
        available=state.google_calendar.configured,
        connections=[_connection_view(r) for r in rows],
    )


@router.post("/google/connect", response_model=ConnectResponse)
async def google_connect(
    body: ConnectRequest,
    claims: Annotated[Claims, Depends(_reader)],
) -> ConnectResponse:
    state = get_state()
    if not state.google_calendar.configured:
        raise _not_configured()
    if not return_to_allowed(body.return_to, settings.calendar_return_to_prefixes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="return_to must be the web app's origin or the notesai:// scheme.",
        )
    token = issue_state(
        tenant_id=claims.tid,
        user_sub=claims.sub,
        return_to=body.return_to.strip(),
        key_hex=settings.calendar_state_hmac_key_hex,
    )
    return ConnectResponse(
        authorize_url=state.google_calendar.authorize_url(state=token, login_hint=body.login_hint)
    )


_DONE_HTML = """<!doctype html>
<meta charset="utf-8"><title>Notes AI</title>
<body style="font-family:system-ui;margin:0;display:grid;place-items:center;height:100vh;color:#1a1816;background:#fff">
<div style="text-align:center;max-width:32rem;padding:2rem">
<h1 style="font-weight:600;font-size:1.25rem">{title}</h1>
<p style="color:#5f5a55">{message}</p>
</div></body>"""


def _done_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(_DONE_HTML.format(title=title, message=message), status_code=status_code)


@router.get("/google/callback", response_model=None, response_class=RedirectResponse)
async def google_callback(
    state: Annotated[str | None, Query()] = None,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> HTMLResponse | RedirectResponse:
    svc = get_state()
    try:
        parsed = verify_state(state, key_hex=settings.calendar_state_hmac_key_hex)
    except InvalidStateError:
        # No trustworthy return_to: a plain page rather than an open redirect.
        return _done_page(
            "This sign-in link has expired",
            "Go back to Notes AI and press Connect Google Calendar again.",
            status_code=400,
        )

    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(_with_query(parsed.return_to, **params), status_code=303)

    if error or not code:
        return back(calendar="error", reason=error or "no_code")
    if not svc.google_calendar.configured:
        return back(calendar="error", reason="not_configured")

    try:
        tokens = await svc.google_calendar.exchange_code(code)
        email = await svc.google_calendar.account_email(tokens.access_token)
    except GoogleError as exc:
        logger.info(
            "calendar.google.connect_failed", extra={"code": exc.code, "status": exc.status}
        )
        return back(calendar="error", reason=exc.code)
    if not tokens.refresh_token:
        # Consent was skipped (a re-authorisation without prompt=consent):
        # without a refresh token the connection would die in an hour.
        return back(calendar="error", reason="no_refresh_token")

    blob = await repo.seal_tokens(
        svc.envelope,
        tenant_id=parsed.tenant_id,
        tokens=repo.StoredTokens(
            access_token=tokens.access_token, refresh_token=tokens.refresh_token
        ),
    )
    async with tenant_connection(svc.app_pool, parsed.tenant_id) as conn:
        row = await repo.upsert(
            conn,
            tenant_id=parsed.tenant_id,
            user_sub=parsed.user_sub,
            provider=parsed.provider,
            account_email=email,
            token_blob=blob,
            token_expires_at=tokens.expires_at,
            scopes=tokens.scopes,
        )
    await svc.audit_writer.write_event(
        tenant_id=parsed.tenant_id,
        kind=audit_kinds.CALENDAR_CONNECTED,
        actor_sub=parsed.user_sub,
        actor_role=None,
        target_kind="calendar_connection",
        target_id=row.id,
        payload={"provider": parsed.provider},
        severity=Severity.INFO,
    )
    return back(calendar="connected", connection_id=str(row.id))


# 0020: bad input answers 400; the calendar's server misbehaving, 502.
_LINK_INPUT_CODES = frozenset(
    {"bad_url", "private_host", "unresolvable", "not_ics", "too_large", "too_many_redirects"}
)


@router.post("/ics/connect", response_model=ConnectionView, status_code=status.HTTP_201_CREATED)
async def ics_connect(
    body: LinkConnectRequest,
    claims: Annotated[Claims, Depends(_reader)],
) -> ConnectionView:
    """Add a calendar by its private iCal address — no Google client, no
    OAuth. The feed is fetched once now so a wrong link fails here, not
    silently on the home page."""
    state = get_state()
    try:
        url = normalize_feed_url(body.url)
        parsed = parse_feed(await state.ics_feeds.fetch(url))
    except FeedError as exc:
        code = (
            status.HTTP_400_BAD_REQUEST
            if exc.code in _LINK_INPUT_CODES
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    label = (body.label or "").strip() or feed_label(parsed, url)
    fingerprint = feed_fingerprint(url)
    blob = await repo.seal_feed_url(state.envelope, tenant_id=claims.tid, url=url)
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # Labels share the (provider, account_email) uniqueness with Google
        # rows; two links with the same calendar name get told apart.
        taken = {
            r.account_email
            for r in await repo.list_live(conn, user_sub=claims.sub)
            if r.provider == "ics" and r.feed_fingerprint != fingerprint
        }
        if label in taken:
            label = f"{label[:110]} ({fingerprint[:6]})"
        row = await repo.insert_feed(
            conn,
            tenant_id=claims.tid,
            user_sub=claims.sub,
            label=label,
            token_blob=blob,
            feed_fingerprint=fingerprint,
        )
    await _audit(claims, audit_kinds.CALENDAR_CONNECTED, row.id, {"provider": "ics"})
    return _connection_view(row)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    connection_id: UUID,
    claims: Annotated[Claims, Depends(_reader)],
) -> None:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.fetch_live(conn, user_sub=claims.sub, connection_id=connection_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such connection.")
        await repo.revoke(conn, connection_id=row.id)
    await _audit(claims, audit_kinds.CALENDAR_DISCONNECTED, row.id, {"provider": row.provider})
    if row.provider != "google":
        return
    # Best effort, after the row is gone from every read path: a dead
    # token at Google is a bonus, not a precondition.
    try:
        tokens = await repo.open_tokens(
            state.envelope, tenant_id=row.tenant_id, token_blob=row.token_blob
        )
        await state.google_calendar.revoke(tokens.refresh_token or tokens.access_token)
    except Exception as exc:  # noqa: BLE001 — the disconnect already happened
        logger.info("calendar.google.revoke_skipped", extra={"error": exc.__class__.__name__})


# ── Calendars of one account ────────────────────────────────────────


@router.get("/connections/{connection_id}/calendars", response_model=CalendarsResponse)
async def list_calendars(
    connection_id: UUID,
    claims: Annotated[Claims, Depends(_reader)],
) -> CalendarsResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.fetch_live(conn, user_sub=claims.sub, connection_id=connection_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such connection.")
        if row.provider == "ics":
            # A link is one calendar; the picker still lets it be switched off.
            return CalendarsResponse(
                connection_id=row.id,
                calendars=[
                    CalendarView(
                        id=FEED_CALENDAR_ID,
                        name=row.account_email,
                        color=None,
                        primary=True,
                        shown=FEED_CALENDAR_ID not in row.hidden_calendar_ids,
                    )
                ],
            )
        try:
            access = await calendar_sync.usable_access_token(
                conn, envelope=state.envelope, google=state.google_calendar, row=row
            )
            calendars = await state.google_calendar.list_calendars(access)
        except (NeedsReauthError, CryptoError):
            await repo.mark_failed(
                conn, connection_id=row.id, error="needs_reauth", needs_reauth=True
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Google asked for a fresh sign-in. Connect the account again.",
            ) from None
        except GoogleError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    hidden = set(row.hidden_calendar_ids)
    return CalendarsResponse(
        connection_id=row.id,
        calendars=[
            CalendarView(
                id=c.id, name=c.name, color=c.color, primary=c.primary, shown=c.id not in hidden
            )
            for c in calendars
        ],
    )


@router.put("/connections/{connection_id}/calendars", response_model=ConnectionView)
async def set_calendars(
    connection_id: UUID,
    body: CalendarsRequest,
    claims: Annotated[Claims, Depends(_reader)],
) -> ConnectionView:
    state = get_state()
    hidden = tuple(dict.fromkeys(h.strip() for h in body.hidden_calendar_ids if h.strip()))
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.fetch_live(conn, user_sub=claims.sub, connection_id=connection_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such connection.")
        await repo.set_hidden_calendars(conn, connection_id=row.id, hidden=hidden)
        updated = await repo.fetch_live(conn, user_sub=claims.sub, connection_id=connection_id)
    assert updated is not None
    return _connection_view(updated)


# ── Events ──────────────────────────────────────────────────────────


@router.get("/events", response_model=EventsResponse)
async def upcoming_events(
    claims: Annotated[Claims, Depends(_reader)],
    days: Annotated[int, Query(ge=1, le=_MAX_DAYS)] = 7,
) -> EventsResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        rows = await repo.list_live(conn, user_sub=claims.sub)
        if not rows:
            return EventsResponse(
                available=state.google_calendar.configured,
                connected=False,
                events=[],
                problems=[],
                fetched_at=_iso(datetime.now(UTC)) or "",
            )
        result = await calendar_sync.upcoming(
            conn,
            envelope=state.envelope,
            google=state.google_calendar,
            user_sub=claims.sub,
            days=days,
            feeds=state.ics_feeds,
        )
    return EventsResponse(
        available=state.google_calendar.configured,
        connected=True,
        events=[
            EventView(
                id=e.id,
                connection_id=item.connection_id,
                account_email=item.account_email,
                calendar_id=e.calendar_id,
                calendar_name=e.calendar_name,
                color=e.color,
                title=e.title,
                start=_iso(e.start) or "",
                end=_iso(e.end) or "",
                all_day=e.all_day,
                location=e.location,
                meeting_url=e.meeting_url,
                html_link=e.html_link,
                attendee_count=e.attendee_count,
                attendees=list(e.attendees),
                organizer=e.organizer,
                response_status=e.response_status,
            )
            for item in result.events
            for e in (item.event,)
        ],
        problems=[
            ProblemView(
                connection_id=p.connection_id,
                account_email=p.account_email,
                code=p.code,
                message=p.message,
                needs_reauth=p.needs_reauth,
            )
            for p in result.problems
        ],
        fetched_at=_iso(datetime.now(UTC)) or "",
    )
