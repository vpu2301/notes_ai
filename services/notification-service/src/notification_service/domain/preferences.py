"""Preference + quiet-hours resolution. Pure: every input, including the clock, is a parameter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notification_events import Category, Channel, EmailMode

from .catalog import spec_for

DEFAULT_TIMEZONE = "Europe/Kyiv"


class SuppressReason(StrEnum):
    """Why a channel will not be dispatched. Persisted on the outbox row."""

    PREFERENCE = "preference"
    QUIET_HOURS = "quiet_hours"
    NO_EMAIL_ADDRESS = "no_email_address"
    DIGEST_DEFERRED = "digest_deferred"
    NOT_DIGEST_ELIGIBLE = "not_digest_eligible"


@dataclass(frozen=True, slots=True)
class UserPreference:
    """A user's explicit override for one category. Absent ⇒ catalog default."""

    in_app_enabled: bool
    email_mode: EmailMode


@dataclass(frozen=True, slots=True)
class UserSettings:
    """Per-user, not per-category."""

    timezone: str = DEFAULT_TIMEZONE
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    digest_hour: int = 8


@dataclass(frozen=True, slots=True)
class ChannelDecision:
    """What to write to the outbox for one channel."""

    channel: Channel
    # False = write the row as `suppressed` with `reason` (queryable), never dispatch.
    dispatch: bool
    reason: SuppressReason | None = None
    # Pending but not due until this instant.
    not_before: datetime | None = None


def resolve_timezone(name: str) -> ZoneInfo:
    """Never raise on bad tz data — fall back and keep delivering."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def in_quiet_hours(settings: UserSettings, at: datetime) -> bool:
    """Is `at` inside the user's local quiet window? [start, end), may wrap midnight."""
    if settings.quiet_hours_start is None or settings.quiet_hours_end is None:
        return False

    local = at.astimezone(resolve_timezone(settings.timezone))
    now_t = local.time()
    start = settings.quiet_hours_start
    end = settings.quiet_hours_end

    if start == end:
        # Zero-width window silences nothing.
        return False
    if start < end:
        return start <= now_t < end
    # Wraps midnight.
    return now_t >= start or now_t < end


def next_quiet_hours_end(settings: UserSettings, at: datetime) -> datetime:
    """First instant after `at` when the quiet window is over (walked in LOCAL time, DST-safe)."""
    if settings.quiet_hours_end is None:
        return at

    tz = resolve_timezone(settings.timezone)
    local = at.astimezone(tz)
    candidate = datetime.combine(local.date(), settings.quiet_hours_end, tzinfo=tz)
    if candidate <= local:
        candidate = datetime.combine(
            local.date() + timedelta(days=1), settings.quiet_hours_end, tzinfo=tz
        )
    return candidate.astimezone(UTC)


def resolve(
    *,
    category: Category,
    preference: UserPreference | None,
    settings: UserSettings,
    now: datetime,
    has_email_address: bool,
) -> tuple[ChannelDecision, ChannelDecision]:
    """Decide both channels for one (user, category). Returns (in_app, email).

    `preference` None = catalog default, resolved here so default changes apply retroactively.
    """
    spec = spec_for(category)

    in_app_enabled = preference.in_app_enabled if preference else spec.default_in_app
    email_mode = preference.email_mode if preference else spec.default_email_mode

    in_app = ChannelDecision(
        channel=Channel.IN_APP,
        dispatch=in_app_enabled,
        reason=None if in_app_enabled else SuppressReason.PREFERENCE,
    )
    # Quiet hours never touch in-app.

    email = _resolve_email(
        category=category,
        email_mode=email_mode,
        settings=settings,
        now=now,
        has_email_address=has_email_address,
    )
    return in_app, email


def _resolve_email(
    *,
    category: Category,
    email_mode: EmailMode,
    settings: UserSettings,
    now: datetime,
    has_email_address: bool,
) -> ChannelDecision:
    spec = spec_for(category)

    def suppressed(reason: SuppressReason) -> ChannelDecision:
        return ChannelDecision(channel=Channel.EMAIL, dispatch=False, reason=reason)

    if email_mode is EmailMode.OFF:
        return suppressed(SuppressReason.PREFERENCE)

    if not has_email_address:
        return suppressed(SuppressReason.NO_EMAIL_ADDRESS)

    if email_mode is EmailMode.DIGEST:
        if not spec.digest_eligible:
            # A preference may not downgrade an unbatchable alert into nothing.
            return _immediate_or_deferred(settings, now)
        # The digest job picks this up.
        return suppressed(SuppressReason.DIGEST_DEFERRED)

    return _immediate_or_deferred(settings, now)


def _immediate_or_deferred(settings: UserSettings, now: datetime) -> ChannelDecision:
    if in_quiet_hours(settings, now):
        # Deferred, not suppressed: the mail still goes after the window.
        return ChannelDecision(
            channel=Channel.EMAIL,
            dispatch=True,
            reason=SuppressReason.QUIET_HOURS,
            not_before=next_quiet_hours_end(settings, now),
        )
    return ChannelDecision(channel=Channel.EMAIL, dispatch=True)
