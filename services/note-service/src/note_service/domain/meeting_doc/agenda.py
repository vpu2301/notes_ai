"""The agenda hiding in a calendar invite's description.

Deterministic, no model. An invite description is mostly boilerplate — a
dial-in block, a Meet link, a signature, a legal footer — with, sometimes,
the three things the organiser actually wants to talk about. Those three
things are worth putting in the note before the meeting starts; nothing
else in the description is.

Rules, in order of how much they matter:

* a line is a candidate when it is **list-like** (bullet, ``1.``, ``a)``)
  or sits under an ``Agenda:`` heading;
* boilerplate — a URL, a phone number, a dial-in/PIN/ID line, an
  unsubscribe or a signature — is dropped wherever it appears;
* 2 to 20 lines survive, each ≤ 160 characters. Fewer than two candidates
  is not a list, and the note gets no agenda at all.

The raw description is never stored and never returned: the caller hands
it in, takes the lines, and drops it (:mod:`routers.notes_meeting`).
"""

from __future__ import annotations

import re
from typing import Final

MIN_LINES: Final = 2
MAX_LINES: Final = 20
MAX_LINE_CHARS: Final = 160
# What a client may send as `calendar.description`. Beyond this an invite
# is a newsletter, not an agenda.
MAX_DESCRIPTION_CHARS: Final = 8192

# "Agenda:", "Tagesordnung", "Порядок денний", "Topics", "Discussion points"
_HEADING = re.compile(
    r"^\s*(?:agenda|topics?|discussion\s+points?|tagesordnung|themen|"
    r"порядок\s+денний|питання)\s*[:：]?\s*$",
    re.IGNORECASE,
)
# A bullet or a number/letter marker. The marker is stripped; what is left
# is the agenda item.
_MARKER = re.compile(r"^[\s>]*(?:[-–—•*·▪◦●○]+|\(?(?:\d{1,2}|[a-zA-Z])[.)])\s+")
_BARE_NUMBER = re.compile(r"^[\s>]*(\d{1,2})[.)]\s*$")

# Boilerplate: the parts of an invite that are plumbing.
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_DIAL_IN = re.compile(
    r"\b(?:dial[- ]?in|phone\s+numbers?|meeting\s*id|passcode|pass\s?code|pin\b|"
    r"join\s+(?:the\s+)?(?:zoom|meeting|call)|google\s+meet|microsoft\s+teams|"
    r"conference\s+id|one\s?tap|einwahl|zugangscode|telefonisch)\b",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{6,}\d(?![\w.])")
_FOOTER = re.compile(
    r"\b(?:unsubscribe|do\s+not\s+(?:reply|forward)|confidential(?:ity)?\s+notice|"
    r"sent\s+from\s+my\s|abmelden|vertraulich)\b",
    re.IGNORECASE,
)
_SIGNATURE = re.compile(r"^\s*(?:--+|__+|—\s*$)")
# HTML: Google hands descriptions over with tags in them.
_TAG = re.compile(r"<[^>]{1,200}>")
_BREAK = re.compile(r"<\s*(?:br\s*/?|/\s*(?:p|div|li|tr))\s*>", re.IGNORECASE)
_ENTITIES: Final = (
    ("&nbsp;", " "),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#39;", "'"),
)


def agenda_lines(description: str | None) -> tuple[str, ...]:
    """The invite's agenda, or ``()`` when it has none.

    ``()`` is the common and correct answer: most invites are a link and a
    room number. An agenda we invented would be worse than no agenda.
    """
    if not description:
        return ()
    lines = _plain_lines(description[:MAX_DESCRIPTION_CHARS])

    under_heading = False
    items: list[str] = []
    seen: set[str] = set()
    pending_number = False
    for raw in lines:
        if _HEADING.match(raw):
            under_heading = True
            continue
        if not raw.strip():
            # A blank line ends the agenda block but not a bulleted list,
            # which carries its own markers.
            under_heading = False
            pending_number = False
            continue
        if _BARE_NUMBER.match(raw):
            # "1." on its own line, the item on the next (common in HTML
            # descriptions flattened to text).
            pending_number = True
            continue

        marked = bool(_MARKER.match(raw))
        item = _MARKER.sub("", raw, count=1).strip() if marked else raw.strip()
        if not (marked or under_heading or pending_number):
            continue
        pending_number = False
        if not _is_agenda_item(item):
            continue
        item = item[:MAX_LINE_CHARS].rstrip()
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) == MAX_LINES:
            break

    return tuple(items) if len(items) >= MIN_LINES else ()


def _plain_lines(description: str) -> list[str]:
    """Description → text lines, HTML flattened."""
    text = _BREAK.sub("\n", description)
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _is_agenda_item(item: str) -> bool:
    """Something a person would read out as a topic."""
    if len(item) < 3:
        return False
    if _URL.search(item) or _DIAL_IN.search(item) or _PHONE.search(item):
        return False
    if _FOOTER.search(item) or _SIGNATURE.match(item):
        return False
    # At least one letter: "2)" and "----" are structure, not topics.
    return any(char.isalpha() for char in item)
