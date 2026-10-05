"""A calendar file for one date a meeting named: RFC 5545, one ``VEVENT``, written
by hand (escaped per §3.3.11, folded at 75 octets per §3.1).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Final

PRODID: Final = "-//notes-ai//key dates//EN"
MAX_SUMMARY: Final = 120


def escape(text: str) -> str:
    """Backslash, semicolon, comma and newlines, in that order."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space,
    never splitting a UTF-8 character."""
    out: list[str] = []
    current = b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 75 if not out else 74
        if len(current) + len(encoded) > limit:
            out.append(current.decode("utf-8"))
            current = b""
        current += encoded
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def event(
    *,
    uid: str,
    summary: str,
    description: str,
    on: date,
    at: time | None = None,
    now: datetime | None = None,
) -> str:
    """One VCALENDAR with one VEVENT: all-day when there is no time, else a
    one-hour event at that local time (floating — the recording did not say
    a time zone, and inventing one would move the deadline)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    if at is None:
        start = f"DTSTART;VALUE=DATE:{on:%Y%m%d}"
        end = f"DTEND;VALUE=DATE:{on + timedelta(days=1):%Y%m%d}"
    else:
        begin = datetime.combine(on, at)
        start = f"DTSTART:{begin:%Y%m%dT%H%M%S}"
        end = f"DTEND:{begin + timedelta(hours=1):%Y%m%dT%H%M%S}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{escape(uid)}",
        f"DTSTAMP:{stamp}",
        start,
        end,
        f"SUMMARY:{escape(summary[:MAX_SUMMARY])}",
        f"DESCRIPTION:{escape(description)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
