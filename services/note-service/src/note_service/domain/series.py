"""Which meetings are the same meeting, week after week: a series key hashed from
the calendar event's iCalendar UID, else the normalised title plus the attendee
set (only with attendees), else nothing. Pure; visibility is decided at the
point of use (ADR-0057).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Final

CALENDAR_UID: Final = "calendar_uid"
TITLE_ATTENDEES: Final = "title_attendees"
MANUAL: Final = "manual"

# A title carries no information below this once it is normalised.
_MIN_TITLE_CHARS: Final = 3
# Titles this generic are not evidence of anything.
_GENERIC_TITLES: Final[frozenset[str]] = frozenset(
    {
        "meeting", "call", "sync", "catch up", "catchup", "check in", "checkin",
        "standup", "stand up", "1 1", "one on one", "weekly", "daily", "monthly",
        "besprechung", "termin", "jour fixe", "зустріч", "дзвінок",
    }
)  # fmt: skip

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_title(title: str) -> str:
    """Lower-cased, punctuation dropped, whitespace collapsed — so
    "Acme <> Us — Weekly" and "acme <> us weekly" are one series."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    return _SPACE.sub(" ", _PUNCT.sub(" ", folded)).strip()


def series_key(
    calendar_context: dict[str, Any] | None,
    *,
    title: str = "",
) -> tuple[str | None, str | None]:
    """``(key, source)``, or ``(None, None)`` for no provable series. A hash, so the
    column holds no content (a UID carries the organiser's domain)."""
    context = calendar_context or {}
    ical_uid = str(context.get("ical_uid") or "").strip()
    if ical_uid:
        return _hash("uid", ical_uid.casefold()), CALENDAR_UID

    names = [str(n).strip() for n in (context.get("attendee_names") or []) if str(n).strip()]
    heading = normalise_title(title or str(context.get("title") or ""))
    if names and len(heading) >= _MIN_TITLE_CHARS and heading not in _GENERIC_TITLES:
        # The attendee SET, order-independent.
        roster = ",".join(sorted({n.casefold() for n in names}))
        return _hash("ta", f"{heading}|{roster}"), TITLE_ATTENDEES
    return None, None


def manual_key(note_id: str) -> str:
    """The key for a hand-linked series, derived from the FIRST note of the chain."""
    return _hash("manual", note_id)


def _hash(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:32]
