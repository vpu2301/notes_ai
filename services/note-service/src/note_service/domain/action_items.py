"""Action items as a derived projection of the ``action_items`` section, parsed
deterministically on first read; recipient responses attach by ``item_key``.

Line grammar: ``[bullet] [Owner:] task [— [by|due] date]``. An explicit
``Name:`` owner is confidence 1.0, two leading capitalised words 0.5. Dates go
through :func:`parse_due`, anchored in the tenant's time zone; unparseable text
keeps its text and has no date.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Literal, Protocol

from ..share_metrics import action_items_materialised
from . import action_items_repository as items_repo
from . import notes_repository as repo

logger = logging.getLogger(__name__)

# Section ids whose lines are action items.
ACTION_SECTION_KEYS = ("action_items", "next_steps")

MAX_TEXT = 500
MAX_OWNER = 60


@dataclass(frozen=True, slots=True)
class ParsedItem:
    text: str
    owner_label: str | None
    owner_confidence: float | None
    due_date: date | None
    due_text: str | None
    due_confidence: float | None
    item_key: str


# ── line grammar ─────────────────────────────────────────────────────

_BULLET = re.compile(r"^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*")
# `:` followed by `//` is a URL scheme, not an owner.
_OWNER = re.compile(r"^(?P<owner>[^:—–\-]{1,60}?):(?!//)\s*(?P<rest>\S.*)$")
# Splits at the FIRST spaced dash, so an ISO date (hyphens, no spaces)
# after it survives and "a 3-year term" inside the task does not split.
_DUE_DASH = re.compile(
    r"^(?P<text>.+?)\s+[—–-]\s*(?:(?:by|due|until|до|bis)\s+)?(?P<due>.+?)\s*$",
    re.IGNORECASE,
)
_DUE_WORD = re.compile(
    r"^(?P<text>.+?)\s+(?:by|due|until|до|bis)\s+(?P<due>.+?)\s*$", re.IGNORECASE
)
_CAP_WORD = re.compile(r"^[A-ZА-ЯІЇЄҐÄÖÜ][\w'’\-]*$")


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".;,").strip().lower()


def item_key(text_norm: str) -> str:
    return hashlib.sha256(text_norm.encode("utf-8")).hexdigest()[:16]


def _split_due(rest: str) -> tuple[str, str | None]:
    for pattern in (_DUE_DASH, _DUE_WORD):
        m = pattern.match(rest)
        if m and m.group("due").strip():
            return m.group("text").strip(), m.group("due").strip()
    return rest.strip(), None


def _inferred_owner(text: str) -> str | None:
    words = text.split()
    if len(words) >= 3 and _CAP_WORD.match(words[0]) and _CAP_WORD.match(words[1]):
        return f"{words[0]} {words[1]}"[:MAX_OWNER]
    return None


def parse_action_lines(text: str, *, anchor: date) -> list[ParsedItem]:
    """Every non-empty line of the section, in order. Pure and deterministic."""
    items: list[ParsedItem] = []
    for raw in text.splitlines():
        line = _BULLET.sub("", raw, count=1).strip()
        if not line:
            continue
        owner: str | None = None
        owner_conf: float | None = None
        m = _OWNER.match(line)
        if m and len(m.group("owner").split()) <= 4:
            owner = m.group("owner").strip()[:MAX_OWNER]
            owner_conf = 1.0
            line = m.group("rest")
        body, due_text = _split_due(line)
        if owner is None:
            owner = _inferred_owner(body)
            owner_conf = 0.5 if owner else None
        due = parse_due(due_text, anchor=anchor) if due_text else None
        body = body[:MAX_TEXT]
        items.append(
            ParsedItem(
                text=body,
                owner_label=owner,
                owner_confidence=owner_conf,
                due_date=due,
                due_text=due_text[:120] if due_text else None,
                due_confidence=(1.0 if due else 0.5) if due_text else None,
                item_key=item_key(normalise_text(body)),
            )
        )
    return items


# ── dates ────────────────────────────────────────────────────────────

_MONTHS: dict[str, int] = {}
for _i, _names in enumerate(
    [
        ("january", "jan", "januar", "jänner", "січня", "січень", "січ"),
        ("february", "feb", "februar", "лютого", "лютий", "лют"),
        ("march", "mar", "märz", "marz", "mär", "mrz", "березня", "березень", "бер"),
        ("april", "apr", "квітня", "квітень", "кві"),
        ("may", "mai", "травня", "травень", "тра"),
        ("june", "jun", "juni", "червня", "червень", "чер"),
        ("july", "jul", "juli", "липня", "липень", "лип"),
        ("august", "aug", "серпня", "серпень", "сер"),
        ("september", "sep", "sept", "вересня", "вересень", "вер"),
        ("october", "oct", "oktober", "okt", "жовтня", "жовтень", "жов"),
        ("november", "nov", "листопада", "листопад", "лис"),
        ("december", "dec", "dezember", "dez", "грудня", "грудень", "гру"),
    ],
    start=1,
):
    for _n in _names:
        _MONTHS[_n] = _i

_WEEKDAYS: dict[str, int] = {}
for _i, _names in enumerate(
    [
        ("monday", "mon", "montag", "понеділок", "понеділка", "пн"),
        ("tuesday", "tue", "tues", "dienstag", "вівторок", "вівторка", "вт"),
        ("wednesday", "wed", "mittwoch", "середа", "середу", "ср"),
        ("thursday", "thu", "thurs", "donnerstag", "четвер", "четверга", "чт"),
        ("friday", "fri", "freitag", "п’ятниця", "п'ятниця", "п’ятницю", "п'ятницю", "пт"),
        ("saturday", "sat", "samstag", "sonnabend", "субота", "суботу", "сб"),
        ("sunday", "sun", "sonntag", "неділя", "неділю", "нд"),
    ]
):
    for _n in _names:
        _WEEKDAYS[_n] = _i

_RELATIVE: dict[str, int] = {
    "today": 0, "сьогодні": 0, "heute": 0,
    "tomorrow": 1, "завтра": 1, "morgen": 1,
    "післязавтра": 2, "übermorgen": 2,
    "next week": 7, "наступного тижня": 7, "nächste woche": 7, "kommende woche": 7,
    "in a week": 7, "через тиждень": 7, "in einer woche": 7,
}  # fmt: skip

_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)")
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|\.)?\s+([^\W\d_]+)\.?(?:,?\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([^\W\d_]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?")


def _month(word: str) -> int | None:
    w = word.lower().rstrip(".")
    return _MONTHS.get(w) or _MONTHS.get(w[:3])


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _with_default_year(month: int, day: int, year: str | None, anchor: date) -> date | None:
    if year:
        y = int(year)
        if y < 100:
            y += 2000
        return _safe_date(y, month, day)
    d = _safe_date(anchor.year, month, day)
    # "by 5 Jan" written in late December means next January.
    if d is not None and d < anchor - timedelta(days=30):
        d = _safe_date(anchor.year + 1, month, day)
    return d


def parse_due(text: str | None, *, anchor: date) -> date | None:
    """A due date from free text, or None. Never raises. Forward-looking: weekdays
    resolve to the next one; the direction-aware reading is :func:`parse_when`."""
    when = _resolve(text, anchor=anchor, direction="future", extended=False)
    return when.date if when else None


# ── dates with a direction ───────────────────────────────────────────

Direction = Literal["future", "past", "auto"]


@dataclass(frozen=True, slots=True)
class ResolvedWhen:
    """A spoken date expression, resolved against the recording day.
    An annotation: the words themselves are never rewritten."""

    date: date
    time: time | None
    direction: str


# Kept out of parse_due so the items projection does not move.
_PAST_RELATIVE: dict[str, int] = {
    "yesterday": -1, "gestern": -1, "вчора": -1, "учора": -1,
    "the day before yesterday": -2, "vorgestern": -2, "позавчора": -2,
    "last week": -7, "letzte woche": -7, "vergangene woche": -7, "letzten woche": -7,
    "vergangenen woche": -7, "минулого тижня": -7,
}  # fmt: skip
_EXTRA_WEEKDAYS: dict[str, int] = {
    "понеділок": 0, "вівторка": 1, "середи": 2, "четверга": 3, "п'ятниці": 4,
    "п’ятниці": 4, "суботи": 5, "неділі": 6,
    "montags": 0, "mittwochs": 2, "freitags": 4,
}  # fmt: skip
_MIDNIGHT = re.compile(r"\b(?:mitternacht|midnight|опівночі|північ)\b")
_CLOCK = re.compile(r"(?<![\d.])(\d{1,2})(?::(\d{2}))?\s*(?:uhr|h\b|o'clock|am\b|pm\b|годин[иі]?)")
_PM = re.compile(r"\bpm\b")


def _clock(s: str) -> time | None:
    if _MIDNIGHT.search(s):
        return time(0, 0)
    m = _CLOCK.search(s)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if _PM.search(s[m.start() : m.end() + 1]) and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_when(
    text: str | None, *, anchor: date, direction: Direction = "future"
) -> ResolvedWhen | None:
    """A date expression (and time, when said) resolved against ``anchor`` in
    ``direction``: ``past`` takes the most recent weekday BEFORE the anchor,
    ``future`` is parse_due's reading, ``auto`` is ``future``. None when nothing resolves."""
    return _resolve(text, anchor=anchor, direction=direction, extended=True)


def _resolve(
    text: str | None, *, anchor: date, direction: Direction, extended: bool
) -> ResolvedWhen | None:
    if not text:
        return None
    past = direction == "past"
    s = re.sub(r"\s+", " ", text.strip().lower()).strip(" .,;:!")
    s = s.replace("’", "'") if extended else s
    at = _clock(s) if extended else None

    def done(d: date | None) -> ResolvedWhen | None:
        return ResolvedWhen(d, at, "past" if past else "future") if d else None

    relative = {**_RELATIVE, **_PAST_RELATIVE} if extended else _RELATIVE
    for phrase, offset in relative.items():
        if s == phrase or s.startswith(phrase + " "):
            return done(anchor + timedelta(days=offset))
    s = re.sub(r"^(?:on|by|due|until|am|bis|у|в|до|next|наступного|nächsten?)\s+", "", s)
    if m := _ISO.search(s):
        return done(_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if m := _NUMERIC.search(s):
        return done(_dated(int(m.group(2)), int(m.group(1)), m.group(3), anchor, past))
    if (m := _DAY_MONTH.search(s)) and (month := _month(m.group(2))):
        return done(_dated(month, int(m.group(1)), m.group(3), anchor, past))
    if (m := _MONTH_DAY.search(s)) and (month := _month(m.group(1))):
        return done(_dated(month, int(m.group(2)), m.group(3), anchor, past))
    first = s.split(" ")[0] if s else ""
    weekdays = {**_WEEKDAYS, **_EXTRA_WEEKDAYS} if extended else _WEEKDAYS
    if first in weekdays:
        wd = weekdays[first]
        if past:
            back = (anchor.weekday() - wd) % 7 or 7
            return done(anchor - timedelta(days=back))
        ahead = (wd - anchor.weekday()) % 7 or 7
        return done(anchor + timedelta(days=ahead))
    return None


def _dated(month: int, day: int, year: str | None, anchor: date, past: bool) -> date | None:
    """A day and month; the next-year roll is for deadlines only."""
    if past and not year:
        return _safe_date(anchor.year, month, day)
    return _with_default_year(month, day, year, anchor)


# ── the seam ─────────────────────────────────────────────────────────


class ActionItemExtractor(Protocol):
    def extract(self, text: str, *, anchor: date) -> list[ParsedItem]: ...


class RulesExtractor:
    """The deterministic parser above. ``MDX_ACTION_ITEM_EXTRACTOR=rules``."""

    def extract(self, text: str, *, anchor: date) -> list[ParsedItem]:
        return parse_action_lines(text, anchor=anchor)


def build_extractor(kind: str) -> ActionItemExtractor:
    if kind != "rules":
        raise ValueError(f"unknown action item extractor {kind!r}")
    return RulesExtractor()


# ── materialisation ──────────────────────────────────────────────────


async def anchor_date(conn: object, *, tenant_id: object) -> date:
    """Today in the tenant's time zone; UTC when the zone is unknown."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    tz_name = await repo.fetch_tenant_timezone(conn, tenant_id=tenant_id)  # type: ignore[arg-type]
    try:
        zone = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001 — a bad zone name is not worth a failed read
        zone = UTC  # type: ignore[assignment]
    return datetime.now(zone).date()


async def materialise_items(
    conn: object,
    *,
    note: repo.NoteRow,
    version: repo.VersionRow,
    anchor: date,
    extractor: ActionItemExtractor | None = None,
) -> int:
    """Insert the item set for ``version``, idempotent via the (version, item_key)
    constraint; a key seen on an earlier version carries its status forward."""
    extractor = extractor or RulesExtractor()
    parsed: list[ParsedItem] = []
    for section in version.content.sections or []:
        if section.section_key in ACTION_SECTION_KEYS and (section.text or "").strip():
            parsed.extend(extractor.extract(section.text, anchor=anchor))
    # Duplicate lines within one version collapse to the first.
    seen: set[str] = set()
    unique = [p for p in parsed if not (p.item_key in seen or seen.add(p.item_key))]  # type: ignore[func-returns-value]
    if not unique:
        return 0
    previous = await items_repo.latest_statuses(
        conn,  # type: ignore[arg-type]
        note_id=note.id,
        keys=[p.item_key for p in unique],
        before_version_id=version.id,
    )
    inserted = await items_repo.insert_items(
        conn,  # type: ignore[arg-type]
        tenant_id=note.tenant_id,
        note_id=note.id,
        version_id=version.id,
        items=unique,
        statuses=previous,
    )
    for p in unique:
        action_items_materialised.add(
            1, {"parsed_owner": p.owner_label is not None, "parsed_due": p.due_date is not None}
        )
    return inserted


async def ensure_items(
    conn: object,
    *,
    note: repo.NoteRow,
    version: repo.VersionRow,
) -> list[items_repo.ItemRow]:
    """The items of ``version``, derived lazily on first read and never re-parsed
    (a version's content is immutable)."""
    items = await items_repo.fetch_items(conn, version_id=version.id)  # type: ignore[arg-type]
    if items:
        return items
    anchor = await anchor_date(conn, tenant_id=note.tenant_id)
    if await materialise_items(conn, note=note, version=version, anchor=anchor) == 0:
        return []
    return await items_repo.fetch_items(conn, version_id=version.id)  # type: ignore[arg-type]
