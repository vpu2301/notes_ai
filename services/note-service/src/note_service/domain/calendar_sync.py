"""Upcoming events across every connection a user has (0019, 0020).

The read path behind ``GET /v1/calendar/events``: for each live
connection — a Google account: refresh the access token when it is about
to expire, list the account's calendars, fetch the chosen ones' events in
parallel; a calendar link (0020): fetch the ICS and expand it — then
merge, drop duplicates (an invite that landed in two calendars), sort by
start, cap.

One connection's failure never hides another's events: it is recorded
on the row (``last_error``, ``needs_reauth``) and reported in the
response's ``problems`` so the client can offer "Sign in again".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from crypto import CryptoError, Envelope

from . import calendar_repository as repo
from .google_calendar import (
    CalendarEvent,
    CalendarInfo,
    GoogleCalendarClient,
    GoogleError,
    NeedsReauthError,
)
from .ics_calendar import (
    FEED_CALENDAR_ID,
    FeedError,
    IcsFeedClient,
    feed_label,
    parse_feed,
    self_email_from_label,
    upcoming_events,
)

logger = logging.getLogger(__name__)

# The merged list the clients render.
MAX_EVENTS = 60
# Refresh a token that has less than this left rather than risk a 401 mid-fan-out.
_REFRESH_MARGIN = timedelta(seconds=90)


@dataclass(frozen=True, slots=True)
class ConnectionProblem:
    connection_id: UUID
    account_email: str
    code: str
    message: str
    needs_reauth: bool


@dataclass(frozen=True, slots=True)
class UpcomingEvent:
    """One event, tagged with the connection it came through."""

    connection_id: UUID
    account_email: str
    event: CalendarEvent


@dataclass(frozen=True, slots=True)
class UpcomingResult:
    events: list[UpcomingEvent]
    problems: list[ConnectionProblem]


async def usable_access_token(
    conn: asyncpg.Connection,
    *,
    envelope: Envelope,
    google: GoogleCalendarClient,
    row: repo.ConnectionRow,
) -> str:
    """The row's access token, refreshed and re-sealed when it is about
    to expire. Raises ``NeedsReauthError`` when Google refuses the refresh."""
    tokens = await repo.open_tokens(envelope, tenant_id=row.tenant_id, token_blob=row.token_blob)
    now = datetime.now(UTC)
    fresh_enough = row.token_expires_at is not None and row.token_expires_at - now > _REFRESH_MARGIN
    if fresh_enough:
        return tokens.access_token
    if not tokens.refresh_token:
        raise NeedsReauthError("no refresh token on file")
    refreshed = await google.refresh(tokens.refresh_token)
    blob = await repo.seal_tokens(
        envelope,
        tenant_id=row.tenant_id,
        tokens=repo.StoredTokens(
            access_token=refreshed.access_token, refresh_token=refreshed.refresh_token
        ),
    )
    await repo.store_tokens(
        conn, connection_id=row.id, token_blob=blob, token_expires_at=refreshed.expires_at
    )
    return refreshed.access_token


def visible_calendars(
    calendars: list[CalendarInfo], *, hidden: tuple[str, ...]
) -> list[CalendarInfo]:
    hidden_set = set(hidden)
    return [c for c in calendars if c.id not in hidden_set]


def merge_events(
    batches: list[list[UpcomingEvent]], *, now: datetime, limit: int = MAX_EVENTS
) -> list[UpcomingEvent]:
    """Flatten, drop what already ended, de-duplicate by iCalUID+start
    (keeping the first copy — calendars are listed primary-first, and
    connections oldest-first), sort by start."""
    seen: set[tuple[str, datetime]] = set()
    out: list[UpcomingEvent] = []
    for batch in batches:
        for item in batch:
            event = item.event
            if event.end <= now:
                continue
            key = (event.ical_uid or event.id, event.start)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=lambda i: (i.event.start, not i.event.all_day, i.event.title.lower()))
    return out[:limit]


async def upcoming_for_feed(
    *,
    envelope: Envelope,
    feeds: IcsFeedClient,
    row: repo.ConnectionRow,
    time_min: datetime,
    time_max: datetime,
) -> list[CalendarEvent]:
    """0020: one calendar link → its occurrences in the window. The link
    is one "calendar" (``FEED_CALENDAR_ID``); switched off in the picker
    means nothing to fetch."""
    if FEED_CALENDAR_ID in row.hidden_calendar_ids:
        return []
    url = await repo.open_feed_url(envelope, tenant_id=row.tenant_id, token_blob=row.token_blob)
    parsed = parse_feed(await feeds.fetch(url))
    calendar = CalendarInfo(
        id=FEED_CALENDAR_ID,
        name=row.account_email or feed_label(parsed, url),
        color=None,
        primary=True,
        selected=True,
    )
    return upcoming_events(
        parsed,
        calendar=calendar,
        time_min=time_min,
        time_max=time_max,
        self_email=self_email_from_label(row.account_email),
    )


async def upcoming_for_connection(
    conn: asyncpg.Connection,
    *,
    envelope: Envelope,
    google: GoogleCalendarClient,
    row: repo.ConnectionRow,
    time_min: datetime,
    time_max: datetime,
    feeds: IcsFeedClient | None = None,
) -> list[CalendarEvent]:
    if row.provider == "ics":
        return await upcoming_for_feed(
            envelope=envelope,
            feeds=feeds or IcsFeedClient(),
            row=row,
            time_min=time_min,
            time_max=time_max,
        )
    access = await usable_access_token(conn, envelope=envelope, google=google, row=row)
    calendars = visible_calendars(
        await google.list_calendars(access), hidden=row.hidden_calendar_ids
    )
    batches = await asyncio.gather(
        *(
            google.list_events(access, calendar, time_min=time_min, time_max=time_max)
            for calendar in calendars
        )
    )
    return [event for batch in batches for event in batch]


async def upcoming(
    conn: asyncpg.Connection,
    *,
    envelope: Envelope,
    google: GoogleCalendarClient,
    user_sub: UUID,
    days: int,
    now: datetime | None = None,
    feeds: IcsFeedClient | None = None,
) -> UpcomingResult:
    current = now or datetime.now(UTC)
    # From the start of today (an all-day event today counts) to N days out.
    time_min = current.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = time_min + timedelta(days=days + 1)
    rows = await repo.list_live(conn, user_sub=user_sub)
    batches: list[list[UpcomingEvent]] = []
    problems: list[ConnectionProblem] = []
    for row in rows:
        try:
            events = await upcoming_for_connection(
                conn,
                envelope=envelope,
                google=google,
                row=row,
                time_min=time_min,
                time_max=time_max,
                feeds=feeds,
            )
            batches.append(
                [
                    UpcomingEvent(connection_id=row.id, account_email=row.account_email, event=e)
                    for e in events
                ]
            )
            await repo.mark_synced(conn, connection_id=row.id)
        except NeedsReauthError as exc:
            await repo.mark_failed(conn, connection_id=row.id, error=exc.code, needs_reauth=True)
            problems.append(
                ConnectionProblem(
                    connection_id=row.id,
                    account_email=row.account_email,
                    code=exc.code,
                    message="Google asked for a fresh sign-in.",
                    needs_reauth=True,
                )
            )
        except (GoogleError, FeedError) as exc:
            await repo.mark_failed(conn, connection_id=row.id, error=exc.code, needs_reauth=False)
            logger.info(
                "calendar.sync_failed",
                extra={"connection_id": str(row.id), "code": exc.code, "status": exc.status},
            )
            problems.append(
                ConnectionProblem(
                    connection_id=row.id,
                    account_email=row.account_email,
                    code=exc.code,
                    message=str(exc),
                    needs_reauth=False,
                )
            )
        except CryptoError as exc:
            # A blob we cannot open is a re-connect, not a crash.
            await repo.mark_failed(
                conn, connection_id=row.id, error="token_unreadable", needs_reauth=True
            )
            logger.warning(
                "calendar.token_unreadable",
                extra={"connection_id": str(row.id), "error": exc.__class__.__name__},
            )
            problems.append(
                ConnectionProblem(
                    connection_id=row.id,
                    account_email=row.account_email,
                    code="token_unreadable",
                    message="The stored sign-in could not be read; connect the account again.",
                    needs_reauth=True,
                )
            )
    return UpcomingResult(events=merge_events(batches, now=current), problems=problems)
