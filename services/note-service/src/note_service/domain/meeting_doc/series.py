"""Which meetings are the same meeting, week after week.

A weekly client call is one conversation held in instalments, and the most
useful line in instalment three is *"still open from last week"*. To say
that, the notes need an edge between them.

The edge is a **series key**, and it is a hash of something stable:

1. the calendar event's **iCalendar UID** — every instance of a recurring
   event shares it, and Sprint 34 already stores it on the note. This is
   the only source that survives a renamed meeting, a moved slot or a
   changed guest list. A one-off event has a unique UID, so it simply
   never matches anything; no special case needed.
2. failing that, the **normalised title plus the attendee set**, and only
   when there are attendees. "Weekly sync" with three different clients
   is three series, and without the attendee half it would be one.
3. failing that, nothing. Two meetings called "Catch-up" are not a series
   on the strength of the word "catch-up".

Everything here is pure, and nothing here decides *whether* a previous
note may be read — that is the visibility rule, enforced at the point of
use (ADR-0057).
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
    """``(key, source)`` — a hex hash and how it was derived, or
    ``(None, None)`` when this meeting belongs to no series we can prove.

    The key is a hash so the column holds no content: an event UID
    contains the organiser's domain, and a title is the customer's name.
    """
    context = calendar_context or {}
    ical_uid = str(context.get("ical_uid") or "").strip()
    if ical_uid:
        return _hash("uid", ical_uid.casefold()), CALENDAR_UID

    names = [str(n).strip() for n in (context.get("attendee_names") or []) if str(n).strip()]
    heading = normalise_title(title or str(context.get("title") or ""))
    if names and len(heading) >= _MIN_TITLE_CHARS and heading not in _GENERIC_TITLES:
        # The attendee SET, order-independent: people join and leave a
        # recurring call, and the organiser's list order is not stable.
        roster = ",".join(sorted({n.casefold() for n in names}))
        return _hash("ta", f"{heading}|{roster}"), TITLE_ATTENDEES
    return None, None


def manual_key(note_id: str) -> str:
    """The key for a series the author linked by hand. Derived from the
    FIRST note of the chain, so every later instalment joins the same one."""
    return _hash("manual", note_id)


def _hash(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:32]
